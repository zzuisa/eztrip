"""地理编码（Mapbox Geocoding v6）：定位反查地址、地址联想。后端代理，不把 token 暴露给任意第三方调用。"""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, List, Optional

import httpx

from ..config import get_settings

_BASE = "https://api.mapbox.com/search/geocode/v6"
_TTL = 3600
# Simplified Chinese everywhere; plain "zh" mixes in Traditional names such as 法國.
LANGUAGE = "zh-Hans"
_cache: Dict[str, Any] = {}
_lock = threading.Lock()


def _feature(f: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    p = f.get("properties") or {}
    c = p.get("coordinates") or {}
    lat, lng = c.get("latitude"), c.get("longitude")
    if lat is None or lng is None:
        xy = (f.get("geometry") or {}).get("coordinates") or []
        if len(xy) >= 2:
            lng, lat = xy[0], xy[1]
    if lat is None or lng is None:
        return None
    ctx = p.get("context") or {}
    city = ""
    for k in ("place", "locality", "district", "region"):
        city = (ctx.get(k) or {}).get("name") or ""
        if city:
            break
    country = ctx.get("country") or {}
    label = p.get("full_address") or ", ".join(x for x in (p.get("name"), p.get("place_formatted")) if x)
    return {
        "label": str(label)[:160],
        "name": str(p.get("name") or "")[:80],
        "lat": float(lat),
        "lng": float(lng),
        "city": city,
        "country": country.get("name") or "",
        "country_code": str(country.get("country_code") or "").upper(),
        "type": p.get("feature_type") or "",
    }


def _get(key: str, path: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
    now = time.time()
    with _lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < _TTL:
            return hit[1]
    token = get_settings().mapbox_access_token
    if not token:
        raise RuntimeError("MAPBOX_ACCESS_TOKEN 未配置")
    with httpx.Client(timeout=8.0) as c:
        r = c.get(_BASE + path, params={**params, "access_token": token, "language": LANGUAGE})
    r.raise_for_status()
    out = [x for x in (_feature(f) for f in (r.json().get("features") or [])) if x]
    with _lock:
        if len(_cache) > 500:
            _cache.clear()
        _cache[key] = (now, out)
    return out


def reverse(lat: float, lng: float) -> Optional[Dict[str, Any]]:
    res = _get("r:%.4f,%.4f" % (lat, lng), "/reverse", {"latitude": lat, "longitude": lng, "limit": 1})
    return res[0] if res else None


def search(q: str, near_lat: Optional[float] = None, near_lng: Optional[float] = None) -> List[Dict[str, Any]]:
    return _search(q, near_lat, near_lng)


AREA_TYPES = ("place", "locality", "district", "region", "country")


def reverse_area(lat: float, lng: float) -> Optional[Dict[str, Any]]:
    """Map click → the surrounding city/area (not the clicked coordinate).

    The returned coordinates are the area's own centre, so the trip is planned around
    a city instead of an arbitrary point. Tries the most specific travel-relevant
    level first and widens only when the click is outside any city (countryside, sea).
    """
    for kind in AREA_TYPES:
        found = _get("a:%s:%.2f,%.2f" % (kind, lat, lng), "/reverse", {"latitude": lat, "longitude": lng, "types": kind, "limit": 1})
        if found:
            hit = dict(found[0])
            hit["area_type"] = kind
            if kind in ("place", "locality", "district") and hit.get("city"):
                hit["name"] = hit["name"] or hit["city"]
            return hit
    return None


def _search(q: str, near_lat: Optional[float] = None, near_lng: Optional[float] = None) -> List[Dict[str, Any]]:
    params: Dict[str, Any] = {"q": q, "limit": 5, "autocomplete": "true"}
    near = ""
    if near_lat is not None and near_lng is not None:
        params["proximity"] = "%.4f,%.4f" % (near_lng, near_lat)
        near = "%.1f,%.1f" % (near_lat, near_lng)
    return _get("s:%s|%s" % (q.strip().lower(), near), "/forward", params)


def search_tourism(q, near_lat=None, near_lng=None):
    """Tourism POIs plus city/address results; bounded and cached like geocoding."""
    key = 'poi:' + q.strip().lower()
    with _lock:
        hit = _cache.get(key)
        if hit and time.time() - hit[0] < _TTL:
            return hit[1]
    out = []
    try:
        from .google_places_service import get_google_places_service
        for p in get_google_places_service().search_places(q, limit=5):
            loc = p.get('location') or {}
            lat, lng = p.get('latitude', loc.get('latitude')), p.get('longitude', loc.get('longitude'))
            if lat is not None and lng is not None:
                out.append({'name': p.get('name') or q, 'label': ' · '.join(filter(None, [p.get('name'), p.get('address')])),
                            'lat': float(lat), 'lng': float(lng), 'type': 'poi', 'city': '', 'country': '', 'country_code': ''})
    except Exception:
        pass
    try:
        out.extend(search(q, near_lat, near_lng))
    except Exception:
        if not out:
            raise
    seen, result = set(), []
    for p in out:
        signature = (round(p['lat'], 4), round(p['lng'], 4))
        if signature not in seen:
            seen.add(signature)
            result.append(p)
    with _lock:
        if len(_cache) > 500:
            _cache.clear()
        _cache[key] = (time.time(), result[:8])
    return result[:8]
