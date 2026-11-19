"""找点乐子：以用户当前位置为圆心，找饭店 / 本地小馆 / 喝一杯 / 娱乐 / 咖啡甜点 / 近期活动。

数据源
- 场所：Google Places API (New) 附近搜索 / 文本搜索（含评分、人均档位、营业状态的字段属 Enterprise 档，约 $35 / 千次，
  每月前 1000 次免费），所以：结果按“约 100 米网格 + 类别 + 半径 + 关键词”缓存 30 分钟，命中不计费不占额度；
  路由层再叠加游客每日额度与全站每日上限。
- 活动：Ticketmaster Discovery API（免费 key，环境变量 TICKETMASTER_API_KEY）。没配置时前端回退为“附近演出/展览场所”。
  这里不让 LLM 编造活动：没有真实数据源就如实说明。
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import threading
import time
PHOTO_TTL_SECONDS = 30 * 86400
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx

from ..config import get_settings

PLACES_TTL = 1800
EVENTS_TTL = 3600
WALK_M_PER_MIN = 80.0
MAX_RADIUS_M = 20000

CATEGORIES: Dict[str, Dict[str, Any]] = {
    "eat": {"label": "吃饭", "types": ["restaurant"]},
    "local": {"label": "本地小馆", "query": "local favorite family-run restaurant", "type": "restaurant", "max_ratings": 1500},
    "drink": {"label": "喝一杯", "types": ["bar", "pub", "wine_bar", "cocktail_bar", "brewery", "beer_garden"]},
    "fun": {"label": "娱乐", "types": ["movie_theater", "bowling_alley", "amusement_center", "karaoke", "video_arcade", "comedy_club", "night_club"]},
    "coffee": {"label": "咖啡甜点", "types": ["cafe", "coffee_shop", "bakery", "dessert_shop", "ice_cream_shop"]},
    "show": {"label": "演出展览场所", "types": ["performing_arts_theater", "concert_hall", "live_music_venue", "event_venue", "cultural_center", "art_gallery"]},
}

_MASK = ",".join("places." + f for f in (
    "id", "displayName", "location", "shortFormattedAddress", "rating", "userRatingCount", "priceLevel",
    "currentOpeningHours", "googleMapsUri", "primaryTypeDisplayName", "editorialSummary", "photos", "businessStatus",
))
_PRICE = {"PRICE_LEVEL_FREE": 0, "PRICE_LEVEL_INEXPENSIVE": 1, "PRICE_LEVEL_MODERATE": 2, "PRICE_LEVEL_EXPENSIVE": 3, "PRICE_LEVEL_VERY_EXPENSIVE": 4}
_PHOTO_REF = re.compile(r"^places/[A-Za-z0-9_\-]{5,200}/photos/[A-Za-z0-9_\-]{5,1200}$")


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lng2 - lng1) / 2) ** 2
    return 6371000.0 * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def valid_photo_ref(ref: str) -> bool:
    return bool(_PHOTO_REF.match(ref or ""))


def clamp_radius(r: Any) -> int:
    try:
        v = int(r)
    except (TypeError, ValueError):
        v = 1500
    return max(300, min(MAX_RADIUS_M, v))


def normalize_place(p: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Google place → 精简结构（不含距离，距离按用户真实位置在读取时再算）。"""
    loc = p.get("location") or {}
    if loc.get("latitude") is None or loc.get("longitude") is None:
        return None
    if str(p.get("businessStatus") or "") in ("CLOSED_PERMANENTLY", "CLOSED_TEMPORARILY"):
        return None
    name = (p.get("displayName") or {}).get("text") or ""
    if not name:
        return None
    photos = p.get("photos") or []
    ref = ""
    if photos and isinstance(photos[0], dict):
        ref = str(photos[0].get("name") or "")
        if not valid_photo_ref(ref):
            ref = ""
    cur = p.get("currentOpeningHours") or {}
    open_now = cur.get("openNow")
    return {
        "id": str(p.get("id") or ""),
        "name": name[:120],
        "lat": float(loc["latitude"]),
        "lng": float(loc["longitude"]),
        "address": str(p.get("shortFormattedAddress") or "")[:140],
        "rating": p.get("rating"),
        "rating_count": p.get("userRatingCount"),
        "price_level": _PRICE.get(str(p.get("priceLevel") or "")),
        "open_now": open_now if isinstance(open_now, bool) else None,
        "maps_url": str(p.get("googleMapsUri") or ""),
        "type_label": str((p.get("primaryTypeDisplayName") or {}).get("text") or "")[:40],
        "summary": str((p.get("editorialSummary") or {}).get("text") or "")[:200],
        "photo_ref": ref,
    }


def decorate(items: List[Dict[str, Any]], lat: float, lng: float, radius_m: int, open_now: bool = False,
             max_ratings: Optional[int] = None) -> List[Dict[str, Any]]:
    """按用户真实位置补距离 / 步行时间，丢掉太远的；可选只要营业中、只要“小而美”。"""
    out: List[Dict[str, Any]] = []
    for it in items:
        d = haversine_m(lat, lng, it["lat"], it["lng"])
        if d > radius_m * 1.15:
            continue
        if open_now and it.get("open_now") is False:
            continue
        if max_ratings and (it.get("rating_count") or 0) > max_ratings:
            continue
        out.append({**it, "distance_m": int(d), "walk_min": max(1, int(round(d / WALK_M_PER_MIN)))})
    return out


def sort_items(items: List[Dict[str, Any]], mode: str) -> List[Dict[str, Any]]:
    if mode == "distance":
        return sorted(items, key=lambda x: x["distance_m"])
    if mode == "rating":
        return sorted(items, key=lambda x: (-(x.get("rating") or 0), -(x.get("rating_count") or 0)))
    # 综合：评分 * 评价量的对数，距离做轻微惩罚
    def score(x: Dict[str, Any]) -> float:
        return (x.get("rating") or 0) * (1 + math.log10(1 + (x.get("rating_count") or 0)) / 3) - x["distance_m"] / 4000.0
    return sorted(items, key=score, reverse=True)


# ---------------------------------------------------------------- 活动（Ticketmaster）


def _tm_image(images: List[Dict[str, Any]]) -> str:
    best = ""
    best_w = 10 ** 9
    for im in images or []:
        w = int(im.get("width") or 0)
        if w >= 500 and w < best_w and str(im.get("url") or "").startswith("https://"):
            best, best_w = str(im["url"]), w
    return best


def normalize_event(e: Dict[str, Any], lat: float, lng: float) -> Optional[Dict[str, Any]]:
    name = str(e.get("name") or "").strip()
    url = str(e.get("url") or "")
    if not name or not url.startswith("https://"):
        return None
    start = (e.get("dates") or {}).get("start") or {}
    venue = (((e.get("_embedded") or {}).get("venues")) or [{}])[0] or {}
    vloc = venue.get("location") or {}
    try:
        vlat, vlng = float(vloc.get("latitude")), float(vloc.get("longitude"))
    except (TypeError, ValueError):
        vlat = vlng = None
    cls = (e.get("classifications") or [{}])[0] or {}
    price = (e.get("priceRanges") or [{}])[0] or {}
    dist = int(haversine_m(lat, lng, vlat, vlng)) if vlat is not None else None
    return {
        "id": str(e.get("id") or ""),
        "name": name[:140],
        "url": url,
        "date": str(start.get("localDate") or ""),
        "time": str(start.get("localTime") or "")[:5],
        "category": str((cls.get("segment") or {}).get("name") or ""),
        "genre": str((cls.get("genre") or {}).get("name") or ""),
        "venue": str(venue.get("name") or "")[:100],
        "address": str((venue.get("address") or {}).get("line1") or "")[:120],
        "city": str((venue.get("city") or {}).get("name") or ""),
        "lat": vlat,
        "lng": vlng,
        "distance_m": dist,
        "price_min": price.get("min"),
        "price_max": price.get("max"),
        "currency": str(price.get("currency") or ""),
        "image": _tm_image(e.get("images") or []),
    }


class FunService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.dir = Path(__file__).resolve().parents[2] / "cache" / "fun"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.photo_dir = Path(__file__).resolve().parents[2] / "storage" / "fun_photos"
        self.photo_dir.mkdir(parents=True, exist_ok=True)
        self._glock = threading.Lock()
        self._locks: Dict[str, threading.Lock] = {}

    # ---------- 缓存
    def _lock(self, key: str) -> threading.Lock:
        with self._glock:
            return self._locks.setdefault(key, threading.Lock())

    def _peek(self, key: str, ttl: int) -> Optional[List[Dict[str, Any]]]:
        try:
            obj = json.loads((self.dir / (key + ".json")).read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return None
        if time.time() - float(obj.get("at", 0)) > ttl:
            return None
        items = obj.get("items")
        return items if isinstance(items, list) else None

    def _store(self, key: str, items: List[Dict[str, Any]]) -> None:
        p = self.dir / (key + ".json")
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps({"at": time.time(), "items": items}, ensure_ascii=False), encoding="utf-8")
        tmp.replace(p)

    @staticmethod
    def places_key(lat: float, lng: float, category: str, radius_m: int, query: str) -> str:
        raw = "p2|%.3f|%.3f|%s|%d|%s" % (lat, lng, category, radius_m, (query or "").strip().lower())
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:40]

    def peek_places(self, lat: float, lng: float, category: str, radius_m: int, query: str) -> Optional[List[Dict[str, Any]]]:
        return self._peek(self.places_key(lat, lng, category, radius_m, query), PLACES_TTL)

    # ---------- 场所
    def _base(self) -> str:
        return (self.settings.google_places_base_url or "https://places.googleapis.com/v1").rstrip("/")

    def _headers(self) -> Dict[str, str]:
        return {"X-Goog-Api-Key": self.settings.google_places_api_key, "X-Goog-FieldMask": _MASK, "Content-Type": "application/json"}

    def fetch_places(self, lat: float, lng: float, category: str, radius_m: int, query: str) -> List[Dict[str, Any]]:
        """同步阻塞（调用方丢线程池）。返回精简列表（已缓存 30 分钟）。"""
        if not self.settings.google_places_api_key:
            raise ValueError("GOOGLE_PLACES_API_KEY 未配置")
        cat = CATEGORIES.get(category)
        if not cat and not query:
            raise ValueError("未知类别")
        key = self.places_key(lat, lng, category, radius_m, query)
        with self._lock(key):
            hit = self._peek(key, PLACES_TTL)
            if hit is not None:
                return hit
            circle = {"center": {"latitude": lat, "longitude": lng}, "radius": float(radius_m)}
            timeout = float(self.settings.google_places_timeout_seconds or 15)
            with httpx.Client(timeout=timeout) as c:
                if query or (cat and cat.get("query")):
                    body: Dict[str, Any] = {
                        "textQuery": query or cat["query"], "languageCode": "zh-CN", "pageSize": 20,
                        "locationBias": {"circle": circle},
                    }
                    if not query and cat and cat.get("type"):
                        body["includedType"] = cat["type"]
                    r = c.post(f"{self._base()}/places:searchText", json=body, headers=self._headers())
                else:
                    body = {
                        "includedTypes": cat["types"], "maxResultCount": 20, "languageCode": "zh-CN",
                        "rankPreference": "POPULARITY", "locationRestriction": {"circle": circle},
                    }
                    r = c.post(f"{self._base()}/places:searchNearby", json=body, headers=self._headers())
            r.raise_for_status()
            items = [x for x in (normalize_place(p) for p in (r.json().get("places") or [])) if x]
            self._store(key, items)
            print(f"[fun] places cat={category} q={bool(query)} r={radius_m} -> {len(items)}")
            return items

    # ---------- 活动
    @staticmethod
    def events_key_configured() -> bool:
        return bool(os.getenv("TICKETMASTER_API_KEY", "").strip())

    def fetch_events(self, lat: float, lng: float, radius_km: int, days: int, keyword: str = "") -> List[Dict[str, Any]]:
        key_api = os.getenv("TICKETMASTER_API_KEY", "").strip()
        if not key_api:
            raise ValueError("TICKETMASTER_API_KEY 未配置")
        raw = "e|%.2f|%.2f|%d|%d|%s|%s" % (lat, lng, radius_km, days, keyword.lower(), datetime.now(timezone.utc).strftime("%Y%m%d%H"))
        key = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:40]
        with self._lock(key):
            hit = self._peek(key, EVENTS_TTL)
            if hit is not None:
                return hit
            now = datetime.now(timezone.utc).replace(microsecond=0)
            params = {
                "apikey": key_api, "latlong": "%.4f,%.4f" % (lat, lng), "radius": radius_km, "unit": "km",
                "startDateTime": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "endDateTime": (now + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "sort": "date,asc", "size": 40,
            }
            if keyword:
                params["keyword"] = keyword
            with httpx.Client(timeout=12.0) as c:
                r = c.get("https://app.ticketmaster.com/discovery/v2/events.json", params=params)
            if r.status_code == 429:
                raise RuntimeError("活动数据源繁忙")
            r.raise_for_status()
            evs = (((r.json().get("_embedded") or {}).get("events")) or [])
            items = [x for x in (normalize_event(e, lat, lng) for e in evs) if x]
            self._store(key, items)
            print(f"[fun] events r={radius_km}km days={days} -> {len(items)}")
            return items

    # ---------- 图片（Google Place Photo，落盘缓存，只代理合法 ref）
    def photo_path(self, ref: str, width: int) -> Path:
        h = hashlib.sha256(("%s|%d" % (ref, width)).encode("utf-8")).hexdigest()[:40]
        return self.photo_dir / (h + ".jpg")

    def photo_cached(self, ref: str, width: int) -> Optional[Path]:
        p = self.photo_path(ref, width)
        if not p.exists():
            return None
        try:
            if time.time() - p.stat().st_mtime > PHOTO_TTL_SECONDS:
                return None  # 超过保留期：重新向 Google 取
        except OSError:
            return None
        return p

    def fetch_photo(self, ref: str, width: int) -> Optional[Path]:
        if not valid_photo_ref(ref) or not self.settings.google_places_api_key:
            return None
        p = self.photo_path(ref, width)
        with self._lock("ph:" + p.name):
            if self.photo_cached(ref, width):
                return p
            with httpx.Client(timeout=12.0) as c:
                r = c.get(f"{self._base()}/{ref}/media", params={"maxWidthPx": width, "skipHttpRedirect": "true"},
                          headers={"X-Goog-Api-Key": self.settings.google_places_api_key})
                if r.status_code != 200:
                    return None
                uri = str(r.json().get("photoUri") or "")
                if not uri.startswith("https://"):
                    return None
                img = c.get(uri, follow_redirects=True)
            mime = img.headers.get("content-type", "").split(";")[0].strip().lower()
            if img.status_code != 200 or mime not in ("image/jpeg", "image/png", "image/webp") or not (2000 <= len(img.content) <= 3_000_000):
                return None
            tmp = p.with_suffix(".tmp")
            tmp.write_bytes(img.content)
            tmp.replace(p)
            return p


_svc: Optional[FunService] = None


def get_fun_service() -> FunService:
    global _svc
    if _svc is None:
        _svc = FunService()
    return _svc
