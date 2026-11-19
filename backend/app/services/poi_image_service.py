"""地点图片解析：Google Places → Wikipedia → Unsplash → 生成式占位图。

- 图片落盘到 storage/poi_photos（随 /app/storage 持久化），以 sha256 键命中，不重复消耗外部配额
- Google key 不暴露：只由后端抓取并代理输出
- 兜底 SVG 永远可用，因此「每个地点都有图」；兜底结果短期后会重试，找到真实图后覆盖同一 key
"""

from __future__ import annotations

import hashlib
import html
import json
import math
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx

from ..config import get_settings

KEY_RE = re.compile(r"^[0-9a-f]{64}$")
MAX_BYTES = 4 * 1024 * 1024
MIN_BYTES = 1500
FALLBACK_RETRY_SECONDS = 6 * 3600
GOOGLE_PHOTO_TTL_SECONDS = int(os.getenv("EZTRIP_PHOTO_TTL_DAYS", "30")) * 86400
UA = "eztrip/1.0 (personal trip planner; contact: admin@roguelife.de)"
_CJK = re.compile(r"[\u3400-\u9fff]")
_EXT = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/svg+xml": "svg"}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def make_key(name: str, lat: Optional[float], lng: Optional[float], kind: str) -> str:
    geo = f"{round(lat, 2)},{round(lng, 2)}" if lat is not None and lng is not None else "-"
    raw = f"{_norm(name)}|{geo}|{kind or 'attraction'}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def fallback_svg(name: str, kind: str = "attraction") -> bytes:
    h = int(hashlib.sha256(_norm(name).encode()).hexdigest()[:6], 16)
    hue = h % 360
    hue2 = (hue + 42) % 360
    initial = html.escape((name or "?").strip()[:1].upper() or "?")
    icon = {"meal": "M", "hotel": "H"}.get(kind, "")
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 500" preserveAspectRatio="xMidYMid slice">'
        f'<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">'
        f'<stop offset="0" stop-color="hsl({hue},62%,58%)"/><stop offset="1" stop-color="hsl({hue2},58%,38%)"/></linearGradient></defs>'
        '<rect width="800" height="500" fill="url(#g)"/>'
        '<circle cx="640" cy="90" r="170" fill="#fff" fill-opacity=".08"/><circle cx="130" cy="430" r="140" fill="#fff" fill-opacity=".07"/>'
        f'<text x="400" y="310" text-anchor="middle" font-size="220" font-weight="700" fill="#fff" fill-opacity=".92" '
        f'font-family="system-ui,-apple-system,Segoe UI,Roboto,Noto Sans SC,sans-serif">{initial}</text>'
        "</svg>"
    )
    return svg.encode("utf-8")


class PoiImageService:
    def __init__(self, base_dir: Optional[Path] = None) -> None:
        self.dir = base_dir or Path(__file__).resolve().parents[2] / "storage" / "poi_photos"
        self.dir.mkdir(parents=True, exist_ok=True)
        self._locks: Dict[str, threading.Lock] = {}
        self._glock = threading.Lock()
        self._unsplash_block_until = 0.0

    # ---------- 缓存 ----------
    def _meta_path(self, key: str) -> Path:
        return self.dir / f"{key}.json"

    def _read_meta(self, key: str) -> Optional[Dict[str, Any]]:
        try:
            return json.loads(self._meta_path(key).read_text(encoding="utf-8"))
        except Exception:
            return None

    def file_for(self, key: str) -> Optional[Tuple[Path, str]]:
        if not KEY_RE.match(key):
            return None
        meta = self._read_meta(key)
        if not meta:
            return None
        p = self.dir / f"{key}.{meta.get('ext', 'jpg')}"
        return (p, meta.get("mime", "image/jpeg")) if p.exists() else None

    def is_cached(self, key: str) -> bool:
        meta = self._read_meta(key)
        if not meta or not self.file_for(key):
            return False
        if meta.get("source") == "fallback":
            return time.time() - float(meta.get("ts", 0)) < FALLBACK_RETRY_SECONDS
        if meta.get("source") == "google" and meta.get("ts") and time.time() - float(meta["ts"]) > GOOGLE_PHOTO_TTL_SECONDS:
            return False  # Google 图片缓存 30 天后重新取，避免长期保存过期内容
        return True

    def _store(self, key: str, data: bytes, mime: str, source: str, credit: str = "", link: str = "", ts: Optional[float] = None) -> Dict[str, Any]:
        ext = _EXT.get(mime, "jpg")
        path = self.dir / f"{key}.{ext}"
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(data)
        tmp.replace(path)
        meta = {"ext": ext, "mime": mime, "source": source, "credit": credit, "link": link, "ts": time.time() if ts is None else ts}
        mp = self._meta_path(key)
        mt = mp.with_suffix(".tmp")
        mt.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        mt.replace(mp)
        return meta

    def _lock(self, key: str) -> threading.Lock:
        with self._glock:
            return self._locks.setdefault(key, threading.Lock())

    # ---------- 外部源 ----------
    def _download(self, client: httpx.Client, url: str, headers: Optional[Dict[str, str]] = None) -> Optional[Tuple[bytes, str]]:
        r = client.get(url, headers=headers or {}, follow_redirects=True)
        if r.status_code != 200:
            return None
        mime = r.headers.get("content-type", "").split(";")[0].strip().lower()
        if mime not in ("image/jpeg", "image/png", "image/webp"):
            return None
        if not (MIN_BYTES <= len(r.content) <= MAX_BYTES):
            return None
        return r.content, mime

    def _google(self, client: httpx.Client, query: str, lat: Optional[float], lng: Optional[float]) -> Optional[Tuple[bytes, str, str, str]]:
        s = get_settings()
        if not s.google_places_api_key:
            return None
        base = (s.google_places_base_url or "https://places.googleapis.com/v1").rstrip("/")
        payload: Dict[str, Any] = {"textQuery": query, "languageCode": "zh-CN", "pageSize": 3}
        if lat is not None and lng is not None:
            payload["locationBias"] = {"circle": {"center": {"latitude": lat, "longitude": lng}, "radius": 3000.0}}
        headers = {
            "X-Goog-Api-Key": s.google_places_api_key,
            "X-Goog-FieldMask": "places.id,places.displayName,places.location,places.photos",
            "Content-Type": "application/json",
        }
        r = client.post(f"{base}/places:searchText", json=payload, headers=headers)
        if r.status_code != 200:
            return None
        for p in (r.json().get("places") or [])[:3]:
            photos = p.get("photos") or []
            if not photos:
                continue
            loc = p.get("location") or {}
            if lat is not None and lng is not None and loc.get("latitude") is not None:
                if _haversine_m(lat, lng, loc["latitude"], loc["longitude"]) > 2500:
                    continue
            ph = photos[0]
            got = self._download(client, f"{base}/{ph['name']}/media?maxWidthPx=1000", {"X-Goog-Api-Key": s.google_places_api_key})
            if got:
                credit = ", ".join(a.get("displayName", "") for a in (ph.get("authorAttributions") or [])[:1])
                return got[0], got[1], credit or "Google Maps", "https://www.google.com/maps/place/?q=place_id:" + str(p.get("id", ""))
        return None

    def _wikipedia(self, client: httpx.Client, name: str, lat: Optional[float], lng: Optional[float]) -> Optional[Tuple[bytes, str, str, str]]:
        langs = ["zh", "en"] if _CJK.search(name) else ["en", "zh"]
        for lang in langs:
            r = client.get(
                f"https://{lang}.wikipedia.org/w/api.php",
                params={
                    "action": "query", "format": "json", "generator": "search", "gsrsearch": name, "gsrlimit": 3,
                    "prop": "pageimages|coordinates", "piprop": "thumbnail", "pithumbsize": 1000, "colimit": 3,
                },
                headers={"User-Agent": UA},
            )
            if r.status_code != 200:
                continue
            pages = sorted(((r.json().get("query") or {}).get("pages") or {}).values(), key=lambda x: x.get("index", 99))
            for pg in pages:
                thumb = (pg.get("thumbnail") or {}).get("source")
                if not thumb:
                    continue
                coords = pg.get("coordinates") or []
                if lat is not None and lng is not None:
                    if not coords:
                        continue
                    if _haversine_m(lat, lng, coords[0]["lat"], coords[0]["lon"]) > 6000:
                        continue
                got = self._download(client, thumb, {"User-Agent": UA})
                if got:
                    return got[0], got[1], "Wikipedia", f"https://{lang}.wikipedia.org/?curid={pg.get('pageid')}"
        return None

    def _unsplash(self, client: httpx.Client, query: str) -> Optional[Tuple[bytes, str, str, str]]:
        s = get_settings()
        if not s.unsplash_access_key or time.time() < self._unsplash_block_until:
            return None
        r = client.get(
            "https://api.unsplash.com/search/photos",
            params={"query": query, "per_page": 1, "orientation": "landscape", "client_id": s.unsplash_access_key},
        )
        if r.status_code in (403, 429):  # demo 限额 50/h
            self._unsplash_block_until = time.time() + 600
            return None
        if r.status_code != 200:
            return None
        results = r.json().get("results") or []
        if not results:
            return None
        u = (results[0].get("urls") or {}).get("regular")
        if not u:
            return None
        got = self._download(client, u)
        if got:
            user = (results[0].get("user") or {})
            return got[0], got[1], "Unsplash · " + str(user.get("name", "")), str((results[0].get("links") or {}).get("html", ""))
        return None

    # ---------- 主入口 ----------
    def resolve(
        self,
        name: str,
        *,
        city: str = "",
        address: str = "",
        lat: Optional[float] = None,
        lng: Optional[float] = None,
        kind: str = "attraction",
        allow_remote: bool = True,
    ) -> Dict[str, Any]:
        """返回 {key, url, source}。allow_remote=False 时只读缓存，未命中返回兜底图。"""
        name = (name or "").strip()[:120]
        kind = kind if kind in ("attraction", "meal", "hotel") else "attraction"
        key = make_key(name, lat, lng, kind)
        url = f"/api/poi/photo/img/{key}"
        if self.is_cached(key):
            return {"key": key, "url": url, "source": (self._read_meta(key) or {}).get("source", "cache")}
        if not allow_remote or not name:
            # 只读缓存：写入「已过期」的兜底图（ts=0），之后允许远程重试
            self._ensure_fallback(key, name or "?", kind, stale=True)
            return {"key": key, "url": url, "source": "fallback"}
        with self._lock(key):
            if self.is_cached(key):
                return {"key": key, "url": url, "source": (self._read_meta(key) or {}).get("source", "cache")}
            hint = " ".join(x for x in (name, address or city) if x)[:200]
            found: Optional[Tuple[bytes, str, str, str]] = None
            source = ""
            try:
                with httpx.Client(timeout=12) as client:
                    for src, fn in (
                        ("google", lambda: self._google(client, hint, lat, lng)),
                        ("wikipedia", lambda: self._wikipedia(client, name, lat, lng)),
                        ("unsplash", lambda: self._unsplash(client, (name + " " + city).strip() if kind != "meal" else ((city + " food restaurant").strip()))),
                    ):
                        try:
                            found = fn()
                        except Exception as exc:  # 单源失败继续下一个
                            print(f"[poi-image] {src} failed for {name!r}: {type(exc).__name__}: {exc}")
                            found = None
                        if found:
                            source = src
                            break
            except Exception as exc:
                print(f"[poi-image] client error {name!r}: {exc}")
            if found:
                data, mime, credit, link = found
                self._store(key, data, mime, source, credit, link)
                return {"key": key, "url": url, "source": source}
            self._ensure_fallback(key, name, kind, force=True)
            return {"key": key, "url": url, "source": "fallback"}

    def _ensure_fallback(self, key: str, name: str, kind: str, force: bool = False, stale: bool = False) -> bool:
        if not force and self.file_for(key):
            return False
        self._store(key, fallback_svg(name, kind), "image/svg+xml", "fallback", ts=0.0 if stale else None)
        return True


_svc: Optional[PoiImageService] = None


def get_poi_image_service() -> PoiImageService:
    global _svc
    if _svc is None:
        _svc = PoiImageService()
    return _svc


def _num(v: Any) -> Optional[float]:
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def item_params(item: Dict[str, Any], default_kind: str, city: str = "") -> Dict[str, Any]:
    return {
        "name": str(item.get("name") or ""),
        "city": city,
        "address": str(item.get("address") or item.get("formatted_address") or ""),
        "lat": _num(item.get("latitude", item.get("lat"))),
        "lng": _num(item.get("longitude", item.get("lng"))),
        "kind": default_kind,
    }


def enrich_payload_images(payload: Dict[str, Any], workers: int = 4) -> bool:
    """同步给 payload 里的景点/餐饮补 image_url（线程池并发）。返回是否有变更。"""
    from concurrent.futures import ThreadPoolExecutor

    svc = get_poi_image_service()
    city = str(payload.get("location") or "")
    targets: List[Tuple[Dict[str, Any], str]] = []
    for a in payload.get("attractions") or []:
        if isinstance(a, dict):
            targets.append((a, "attraction"))
    for day in payload.get("itinerary") or []:
        if not isinstance(day, dict):
            continue
        for a in day.get("activities") or []:
            if isinstance(a, dict):
                targets.append((a, "attraction"))
        for m in day.get("meals") or []:
            if isinstance(m, dict):
                targets.append((m, "meal"))
    todo = [(it, k) for it, k in targets if it.get("name") and not it.get("image_url")]
    # 同名同地只解析一次
    def job(pair):
        it, k = pair
        return svc.resolve(**item_params(it, k, city))

    changed = False
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for (it, _k), res in zip(todo, ex.map(job, todo)):
            url = res["url"]
            it["image_url"] = url
            it["photo_url"] = url
            it["thumbnail"] = url
            it["image"] = url
            changed = True
    return changed

