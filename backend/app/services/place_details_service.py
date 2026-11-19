"""地点详情（评论 / 星标 / 营业时间）：Google Places API (New) 按需取数 + 磁盘缓存。

费用控制（评论字段属于 Atmosphere 档，约 $40 / 千次，每月前 1000 次免费）：
- 只在用户打开地点详情时才取，行程生成流程不调用；
- 结果按“地点”缓存 3 天（含“查无此地”的负缓存 6 小时），命中缓存不计费也不占游客额度；
- 并发相同地点合并成一次上游请求；
- 路由层再叠加游客每日额度与全站每日上限。
Google 的 reviews 最多返回 5 条且只按相关度排序，这里按发布时间倒序展示；展示时必须保留 Google 署名与查看全部评论的链接。
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from ..config import get_settings

TTL_SECONDS = 3 * 24 * 3600
NEG_TTL_SECONDS = 6 * 3600
MATCH_RADIUS_M = 2500.0
MAX_REVIEW_CHARS = 600

_FIELDS = (
    "id,displayName,location,rating,userRatingCount,reviews,reviewSummary,regularOpeningHours,currentOpeningHours,"
    "utcOffsetMinutes,websiteUri,nationalPhoneNumber,googleMapsUri,priceLevel,priceRange,businessStatus"
)
_TEXT_MASK = ",".join("places." + f for f in _FIELDS.split(","))
_TEXT_MASK_SAFE = ",".join("places." + f for f in _FIELDS.split(",") if f != "reviewSummary")
_DETAIL_MASK_SAFE = ",".join(f for f in _FIELDS.split(",") if f != "reviewSummary")

_PRICE_LEVEL = {
    "PRICE_LEVEL_FREE": 0, "PRICE_LEVEL_INEXPENSIVE": 1, "PRICE_LEVEL_MODERATE": 2,
    "PRICE_LEVEL_EXPENSIVE": 3, "PRICE_LEVEL_VERY_EXPENSIVE": 4,
}
_NORM = re.compile(r"[\s\-_·・,，.。'’\"()（）]+")


def _norm(s: str) -> str:
    return _NORM.sub("", (s or "").lower())


def _haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lng2 - lng1) / 2) ** 2
    return 6371000.0 * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def cache_key(name: str, lat: Optional[float], lng: Optional[float], place_id: str = "") -> str:
    if place_id:
        raw = "id:" + place_id
    else:
        raw = "nm:%s|%s|%s" % (_norm(name), "" if lat is None else "%.3f" % lat, "" if lng is None else "%.3f" % lng)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:40]


def _money(m: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not isinstance(m, dict):
        return None
    try:
        return {"currency": m.get("currencyCode") or "", "value": float(m.get("units") or 0) + float(m.get("nanos") or 0) / 1e9}
    except (TypeError, ValueError):
        return None


def normalize(p: Dict[str, Any]) -> Dict[str, Any]:
    """把 Google 返回的 place 压成前端要用的精简结构。"""
    reviews: List[Dict[str, Any]] = []
    for r in p.get("reviews") or []:
        if not isinstance(r, dict):
            continue
        text = ((r.get("text") or {}).get("text") or (r.get("originalText") or {}).get("text") or "").strip()
        author = r.get("authorAttribution") or {}
        reviews.append({
            "author": str(author.get("displayName") or "Google 用户")[:40],
            "author_url": author.get("uri") or "",
            "rating": r.get("rating"),
            "text": text[:MAX_REVIEW_CHARS],
            "time": r.get("publishTime") or "",
            "relative": r.get("relativePublishTimeDescription") or "",
            "url": r.get("googleMapsUri") or "",
        })
    reviews.sort(key=lambda x: x["time"], reverse=True)  # Google 只给 5 条且按相关度，这里仅把最近的排前面

    opening: Optional[Dict[str, Any]] = None
    reg = p.get("regularOpeningHours") or {}
    cur = p.get("currentOpeningHours") or {}
    weekday = [str(x) for x in (reg.get("weekdayDescriptions") or cur.get("weekdayDescriptions") or [])]
    if weekday or "openNow" in reg or "openNow" in cur:
        today = None
        off = p.get("utcOffsetMinutes")
        if isinstance(off, (int, float)):
            local = datetime.now(timezone.utc) + timedelta(minutes=int(off))
            today = local.weekday()  # 周一=0，与 weekdayDescriptions 顺序一致
        opening = {
            "open_now": cur.get("openNow", reg.get("openNow")),
            "weekday_text": weekday,
            "today_index": today,
        }
    summary = ((p.get("reviewSummary") or {}).get("text") or {}).get("text") or ""
    loc = p.get("location") or {}
    return {
        "place_id": p.get("id") or "",
        "name": (p.get("displayName") or {}).get("text") or "",
        "latitude": loc.get("latitude"),
        "longitude": loc.get("longitude"),
        "rating": p.get("rating"),
        "rating_count": p.get("userRatingCount"),
        "reviews": reviews,
        "review_summary": summary,
        "opening": opening,
        "website": p.get("websiteUri") or "",
        "phone": p.get("nationalPhoneNumber") or "",
        "maps_url": p.get("googleMapsUri") or "",
        "price_level": _PRICE_LEVEL.get(str(p.get("priceLevel") or ""), None),
        "price_range": {"start": _money((p.get("priceRange") or {}).get("startPrice")), "end": _money((p.get("priceRange") or {}).get("endPrice"))} if p.get("priceRange") else None,
        "status": p.get("businessStatus") or "",
        "fetched_at": int(time.time()),
    }


def pick_best(places: List[Dict[str, Any]], name: str, lat: Optional[float], lng: Optional[float]) -> Optional[Dict[str, Any]]:
    """名称相近且距离合理的优先；有坐标时超出半径的一律丢弃，避免把同名的别处评论贴过来。"""
    want = _norm(name)
    scored = []
    for p in places:
        loc = p.get("location") or {}
        dist = None
        if lat is not None and lng is not None and loc.get("latitude") is not None:
            dist = _haversine_m(lat, lng, float(loc["latitude"]), float(loc["longitude"]))
            if dist > MATCH_RADIUS_M:
                continue
        got = _norm((p.get("displayName") or {}).get("text") or "")
        name_ok = bool(want and got and (want in got or got in want))
        scored.append((0 if name_ok else 1, dist if dist is not None else 0.0, p))
    if not scored:
        return None
    scored.sort(key=lambda t: (t[0], t[1]))
    best = scored[0]
    if best[0] == 1 and (lat is None or lng is None):
        return None  # 没坐标又对不上名字，宁可不显示
    return best[2]


class PlaceDetailsService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.dir = Path(__file__).resolve().parents[2] / "cache" / "place_details"
        self.dir.mkdir(parents=True, exist_ok=True)
        self._glock = threading.Lock()
        self._locks: Dict[str, threading.Lock] = {}

    # ---------- 缓存 ----------
    def _path(self, key: str) -> Path:
        return self.dir / (key + ".json")

    def peek(self, key: str) -> Optional[Dict[str, Any]]:
        """命中返回 {"data": {...}|None, "at": ts}（data 为 None 表示负缓存）；未命中/过期返回 None。"""
        p = self._path(key)
        try:
            obj = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return None
        ttl = TTL_SECONDS if obj.get("data") else NEG_TTL_SECONDS
        if time.time() - float(obj.get("at", 0)) > ttl:
            return None
        return obj

    def _store(self, key: str, data: Optional[Dict[str, Any]]) -> None:
        p = self._path(key)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps({"at": time.time(), "data": data}, ensure_ascii=False), encoding="utf-8")
        tmp.replace(p)

    def _lock(self, key: str) -> threading.Lock:
        with self._glock:
            return self._locks.setdefault(key, threading.Lock())

    # ---------- 上游 ----------
    def _base(self) -> str:
        return (self.settings.google_places_base_url or "https://places.googleapis.com/v1").rstrip("/")

    def _headers(self, mask: str) -> Dict[str, str]:
        return {"X-Goog-Api-Key": self.settings.google_places_api_key, "X-Goog-FieldMask": mask, "Content-Type": "application/json"}

    def _fetch(self, name: str, city: str, lat: Optional[float], lng: Optional[float], place_id: str) -> Optional[Dict[str, Any]]:
        if not self.settings.google_places_api_key:
            raise ValueError("GOOGLE_PLACES_API_KEY 未配置")
        timeout = float(self.settings.google_places_timeout_seconds or 15)
        with httpx.Client(timeout=timeout) as c:
            if place_id:
                r = c.get(f"{self._base()}/places/{place_id}", params={"languageCode": "zh-CN"}, headers=self._headers(",".join(_FIELDS.split(","))))
                if r.status_code == 400:
                    r = c.get(f"{self._base()}/places/{place_id}", params={"languageCode": "zh-CN"}, headers=self._headers(_DETAIL_MASK_SAFE))
                if r.status_code == 404:
                    return None
                r.raise_for_status()
                return r.json()
            body: Dict[str, Any] = {"textQuery": ("%s %s" % (name, city)).strip(), "languageCode": "zh-CN", "pageSize": 3}
            if lat is not None and lng is not None:
                body["locationBias"] = {"circle": {"center": {"latitude": lat, "longitude": lng}, "radius": 1500.0}}
            r = c.post(f"{self._base()}/places:searchText", json=body, headers=self._headers(_TEXT_MASK))
            if r.status_code == 400:  # reviewSummary 个别区域/版本不支持时降级重试
                r = c.post(f"{self._base()}/places:searchText", json=body, headers=self._headers(_TEXT_MASK_SAFE))
            r.raise_for_status()
            return pick_best(r.json().get("places") or [], name, lat, lng)

    def lookup(self, name: str, city: str, lat: Optional[float], lng: Optional[float], place_id: str = "") -> Optional[Dict[str, Any]]:
        """同步阻塞（调用方丢线程池）。返回精简详情；查无此地返回 None（并写负缓存）。"""
        key = cache_key(name, lat, lng, place_id)
        with self._lock(key):
            hit = self.peek(key)
            if hit is not None:
                return hit["data"]
            raw = self._fetch(name, city, lat, lng, place_id)
            data = normalize(raw) if raw else None
            self._store(key, data)
            print(f"[place-details] fetched name={name!r} found={bool(data)} reviews={len((data or {}).get('reviews') or [])}")
            return data


_svc: Optional[PlaceDetailsService] = None


def get_place_details_service() -> PlaceDetailsService:
    global _svc
    if _svc is None:
        _svc = PlaceDetailsService()
    return _svc

