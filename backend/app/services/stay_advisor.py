"""住宿推荐（片区 + 候选酒店）：先由 AI 依据整趟行程的景点分布推荐 2-3 个“住哪一片”，
再用 Google Places 在每个片区里找真实酒店，并按“到全部行程点的平均距离”排序。

不接 Airbnb / Booking 的数据（无官方公开接口、抓取违反条款）：前端只生成带城市/日期/人数的站内搜索深链，用户自行点开比价预订。
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from ..config import get_settings
from . import voice as _voice

CACHE_TTL = 7 * 24 * 3600
MAX_AREAS = 3
HOTELS_PER_AREA = 4
MAX_POINTS = 40

_PREF_KEYWORD = {
    "经济": "budget hotel", "舒适": "hotel", "豪华": "luxury hotel", "民宿": "guesthouse apartment",
}
_PRICE = {"PRICE_LEVEL_INEXPENSIVE": 1, "PRICE_LEVEL_MODERATE": 2, "PRICE_LEVEL_EXPENSIVE": 3, "PRICE_LEVEL_VERY_EXPENSIVE": 4}
_MASK = "places.id,places.displayName,places.location,places.formattedAddress,places.rating,places.userRatingCount,places.priceLevel,places.googleMapsUri,places.types"


def _clip(v: Any, n: int) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()[:n]


def km(a: tuple, b: tuple) -> float:
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    h = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(b[1] - a[1]) / 2) ** 2
    return 6371.0 * 2 * math.atan2(math.sqrt(h), math.sqrt(1 - h))


def clean_pref(raw: str) -> str:
    """住宿偏好来自查询参数：只留中文/字母数字和常见分隔符，限长。"""
    return re.sub(r"[^\w一-鿿、，,/ +·-]", "", str(raw or ""))[:60].strip()


def keyword_for(pref: str) -> str:
    for k, v in _PREF_KEYWORD.items():
        if k in (pref or ""):
            return v
    return "hotel"


# ---------------------------------------------------------------- 行程点


def collect_points(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for d in [x for x in (payload.get("itinerary") or []) if isinstance(x, dict)]:
        day = int(d.get("day") or 0) or 1
        for it in list(d.get("activities") or []) + list(d.get("meals") or []):
            if not isinstance(it, dict):
                continue
            try:
                lat, lng = float(it.get("latitude")), float(it.get("longitude"))
            except (TypeError, ValueError):
                continue
            if abs(lat) > 90 or abs(lng) > 180 or (lat == 0 and lng == 0):
                continue
            out.append({"day": day, "name": _clip(it.get("name"), 40), "lat": lat, "lng": lng})
    return out[:MAX_POINTS * 2]


def centroid(points: List[Dict[str, Any]]) -> tuple:
    return (sum(p["lat"] for p in points) / len(points), sum(p["lng"] for p in points) / len(points))


def day_centroids(points: List[Dict[str, Any]]) -> Dict[int, tuple]:
    by: Dict[int, List[Dict[str, Any]]] = {}
    for p in points:
        by.setdefault(p["day"], []).append(p)
    return {d: centroid(v) for d, v in by.items()}


# ---------------------------------------------------------------- AI 选片区


def build_messages(payload: Dict[str, Any], points: List[Dict[str, Any]], pref: str) -> List[Dict[str, str]]:
    c = centroid(points)
    spread = max(km(c, (p["lat"], p["lng"])) for p in points)
    lines = []
    for d, dc in sorted(day_centroids(points).items()):
        names = "、".join(p["name"] for p in points if p["day"] == d)[:260]
        lines.append(f"第{d}天（重心 {dc[0]:.4f},{dc[1]:.4f}）：{names}")
    system = (
        "你是资深旅行住宿顾问。根据用户整趟行程各天的景点分布，推荐 2-3 个最适合“住下来”的片区/街区（不是具体酒店）。"
        "判断依据：到各天景点的往返便利度、公共交通/步行、夜间氛围与安全感、预算偏好。每个片区必须是真实存在的地名。"
        "只输出一个 JSON 对象，不要任何解释，格式："
        '{"summary":"一句话总结住宿思路(≤60字)","areas":[{"name":"片区中文名(必要时附当地名)","query":"用于地图搜索的\\"片区, 城市\\"，用当地常用拼写",'
        '"why":"推荐理由(≤70字)","best_for":"适合谁(≤24字)","pros":["优点≤18字"],"cons":["缺点≤18字"],"transit":"交通要点(≤40字)"}]}。'
        "pros/cons 各 2-3 条；不要编造酒店名称、价格、具体班次。使用简体中文。"
        + "\n" + _voice.VOICE_COPY
    )
    user = (
        f"目的地：{payload.get('location', '')}，共 {payload.get('days', len(day_centroids(points)))} 天。\n"
        f"住宿偏好：{pref or '未指定'}。景点最大分散半径约 {spread:.1f} km。\n" + "\n".join(lines)
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _extract_json(content: str) -> Optional[Dict[str, Any]]:
    s = (content or "").strip()
    s = re.sub(r"^```(?:json)?\s*|\s*```$", "", s, flags=re.I)
    i, j = s.find("{"), s.rfind("}")
    if i < 0 or j <= i:
        return None
    try:
        obj = json.loads(s[i:j + 1])
    except Exception:
        return None
    return obj if isinstance(obj, dict) else None


def parse_areas(content: str) -> Optional[Dict[str, Any]]:
    raw = _extract_json(content)
    if not raw:
        return None
    areas = []
    seen = set()
    for a in raw.get("areas") or []:
        if not isinstance(a, dict):
            continue
        name = _clip(a.get("name"), 40)
        query = _clip(a.get("query"), 80) or name
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        areas.append({
            "name": name, "query": query, "why": _clip(a.get("why"), 90), "best_for": _clip(a.get("best_for"), 30),
            "pros": [_clip(x, 24) for x in (a.get("pros") or []) if _clip(x, 24)][:3],
            "cons": [_clip(x, 24) for x in (a.get("cons") or []) if _clip(x, 24)][:3],
            "transit": _clip(a.get("transit"), 50),
        })
        if len(areas) >= MAX_AREAS:
            break
    if not areas:
        return None
    return _voice.scrub_value({"summary": _clip(raw.get("summary"), 80), "areas": areas})


# ---------------------------------------------------------------- 酒店检索与排序


def rank_hotels(places: List[Dict[str, Any]], points: List[Dict[str, Any]], limit: int = HOTELS_PER_AREA) -> List[Dict[str, Any]]:
    """places 为 Google 原始结果；过滤低质量，附上到行程点的距离，按“评分×距离”综合排序。"""
    dcs = day_centroids(points)
    out, seen = [], set()
    for p in places:
        loc = p.get("location") or {}
        if loc.get("latitude") is None:
            continue
        pt = (float(loc["latitude"]), float(loc["longitude"]))
        name = _clip((p.get("displayName") or {}).get("text"), 60)
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        rating, cnt = p.get("rating"), p.get("userRatingCount") or 0
        if rating is not None and (float(rating) < 3.8 or cnt < 20):
            continue
        dists = [km(pt, (q["lat"], q["lng"])) for q in points]
        avg = sum(dists) / len(dists)
        out.append({
            "name": name, "address": _clip(p.get("formattedAddress"), 120), "latitude": pt[0], "longitude": pt[1],
            "rating": rating, "rating_count": cnt or None, "price_level": _PRICE.get(str(p.get("priceLevel") or "")),
            "maps_url": p.get("googleMapsUri") or "", "place_id": p.get("id") or "",
            "avg_km": round(avg, 1), "max_km": round(max(dists), 1),
            "day_km": {str(d): round(km(pt, c), 1) for d, c in dcs.items()},
        })
    # 距离越近越好，评分越高越好：评分每高 0.1 约抵 0.35 km
    out.sort(key=lambda h: h["avg_km"] - (float(h["rating"] or 4.0) - 4.0) * 3.5)
    return out[:limit]


class HotelSearch:
    """Google Places Text Search（includedType=lodging），结果缓存 7 天。"""

    def __init__(self) -> None:
        self.s = get_settings()
        self.dir = Path(__file__).resolve().parents[2] / "cache" / "stay_hotels"
        self.dir.mkdir(parents=True, exist_ok=True)

    def search(self, area_query: str, keyword: str, anchor: Optional[tuple], radius_m: float) -> List[Dict[str, Any]]:
        if not self.s.google_places_api_key:
            raise ValueError("GOOGLE_PLACES_API_KEY 未配置")
        q = f"{keyword} {area_query}".strip()
        key = hashlib.sha256(f"lodging-v2|{q}|{anchor}|{int(radius_m)}".encode()).hexdigest()[:40]
        p = self.dir / (key + ".json")
        try:
            obj = json.loads(p.read_text(encoding="utf-8"))
            if time.time() - float(obj.get("at", 0)) < CACHE_TTL:
                return obj["places"]
        except Exception:
            pass
        base = (self.s.google_places_base_url or "https://places.googleapis.com/v1").rstrip("/")
        body = {
            "textQuery": q, "languageCode": "zh-CN", "pageSize": 10, "includedType": "lodging", "strictTypeFiltering": True,
            "locationBias": {"circle": {"center": {"latitude": anchor[0], "longitude": anchor[1]}, "radius": min(50000.0, max(2000.0, radius_m))}} if anchor else None,
        }
        if anchor is None:
            body.pop("locationBias", None)
        with httpx.Client(timeout=float(self.s.google_places_timeout_seconds or 15)) as c:
            r = c.post(f"{base}/places:searchText", json=body, headers={
                "X-Goog-Api-Key": self.s.google_places_api_key, "X-Goog-FieldMask": _MASK, "Content-Type": "application/json"})
            r.raise_for_status()
            places = r.json().get("places") or []
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps({"at": time.time(), "places": places}, ensure_ascii=False), encoding="utf-8")
        tmp.replace(p)
        return places


def area_stats(hotels: List[Dict[str, Any]], points: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not hotels:
        return {}
    c = (sum(h["latitude"] for h in hotels) / len(hotels), sum(h["longitude"] for h in hotels) / len(hotels))
    avg = sum(km(c, (p["lat"], p["lng"])) for p in points) / len(points)
    return {"latitude": c[0], "longitude": c[1], "avg_km": round(avg, 1)}


_hs: Optional[HotelSearch] = None


def get_hotel_search() -> HotelSearch:
    global _hs
    if _hs is None:
        _hs = HotelSearch()
    return _hs

