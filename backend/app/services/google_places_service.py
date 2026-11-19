"""Google Places API (New) 服务封装"""

import hashlib
import json
import math
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from ..config import get_settings
from . import opening_hours as oh


class GooglePlacesService:
    """Google Places API(New) 服务"""

    # types / primaryType 与 rating 同属 Enterprise 档位的同一次请求，不额外计费；用来判断“是否收门票”（比名称关键词准得多）
    FIELD_MASK = "places.displayName,places.location,places.formattedAddress,places.rating,places.editorialSummary,places.types,places.primaryType,places.regularOpeningHours,places.businessStatus"
    # 缓存键沿用旧字段集，避免加字段后整库缓存失效、白白重新计费（旧缓存没有 types 时退回关键词判断）
    _CACHE_KEY_MASK = "places.displayName,places.location,places.formattedAddress,places.rating,places.editorialSummary"
    _FREE_TYPES = {"park", "city_park", "national_park", "state_park", "garden", "botanical_garden", "plaza", "town_square", "monument",
                   "statue", "sculpture", "church", "place_of_worship", "hindu_temple", "mosque", "synagogue", "cemetery", "beach",
                   "hiking_area", "marina", "bridge", "pedestrian_street", "scenic_spot", "playground", "dog_park", "visitor_center",
                   "farmers_market", "market", "shopping_mall", "store", "restaurant", "cafe", "bakery", "bar", "coffee_shop"}
    _PAID_TYPES = (("amusement_park", 30), ("water_park", 25), ("zoo", 22), ("aquarium", 22), ("spa", 25), ("wellness_center", 25),
                   ("museum", 15), ("art_gallery", 12), ("planetarium", 12), ("observation_deck", 14), ("castle", 14), ("stadium", 20),
                   ("performing_arts_theater", 25), ("opera_house", 25), ("concert_hall", 25), ("movie_theater", 10))
    CACHE_TTL_SECONDS = 7 * 24 * 60 * 60

    def __init__(self):
        self.settings = get_settings()
        self.cache_dir = Path(__file__).resolve().parents[2] / "cache" / "google_places"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _log(self, stage: str, msg: str) -> None:
        ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        print(f"{ts} [google-places][{stage}] {msg}")

    def _cache_key(self, query: str, limit: int) -> str:
        raw = json.dumps({"query": query.strip().lower(), "limit": limit, "field_mask": self._CACHE_KEY_MASK}, ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _cache_path(self, key: str) -> Path:
        return self.cache_dir / f"{key}.json"

    def _read_cache(self, key: str) -> List[Dict[str, Any]] | None:
        path = self._cache_path(key)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            saved_at = float(payload.get("saved_at", 0))
            if time.time() - saved_at > self.CACHE_TTL_SECONDS:
                try:
                    path.unlink()
                except Exception:
                    pass
                return None
            result = payload.get("result")
            if isinstance(result, list):
                self._log("cache_hit", f"✅ 命中缓存 query={payload.get('query', '')} limit={payload.get('limit', 0)} path={path.name}")
                return result
        except Exception as exc:
            self._log("cache_read_error", f"query_cache_error={exc}")
        return None

    def _write_cache(self, key: str, query: str, limit: int, result: List[Dict[str, Any]]) -> None:
        path = self._cache_path(key)
        payload = {
            "saved_at": time.time(),
            "query": query,
            "limit": limit,
            "result": result,
        }
        try:
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            self._log("cache_write", f"📝 缓存写入 query={query} limit={limit} path={path.name}")
        except Exception as exc:
            self._log("cache_write_error", f"query_cache_error={exc}")

    def _build_curl_command(self, url: str, headers: Dict[str, str], payload: Dict[str, Any]) -> str:
        payload_json = json.dumps(payload, ensure_ascii=False)
        escaped_payload = payload_json.replace("'", "'\"'\"'")
        return (
            "curl -X POST "
            f"'{url}' "
            f"-H 'X-Goog-Api-Key: {headers.get('X-Goog-Api-Key', '')}' "
            f"-H 'X-Goog-FieldMask: {headers.get('X-Goog-FieldMask', '')}' "
            "-H 'Content-Type: application/json' "
            f"--data-raw '{escaped_payload}'"
        )

    def _price_from_types(self, place: Dict[str, Any]) -> Optional[float]:
        """按 Google 的地点类型判断门票：收费类型给参考价，公共空间 / 宗教场所 / 商铺 / 餐饮记 0；判断不了返回 None。"""
        types = [t for t in ([place.get("primaryType")] + list(place.get("types") or [])) if t]
        if not types:
            return None
        primary = types[0]
        for t, price in self._PAID_TYPES:
            if t in types:
                return float(price)
        if primary in self._FREE_TYPES:
            return 0.0
        if any(t in self._FREE_TYPES for t in types) and "tourist_attraction" not in types[:2]:
            return 0.0
        return None

    def _estimate_ticket_price(self, name: str, place: Dict[str, Any]) -> float:
        by_type = self._price_from_types(place)
        if by_type is not None:
            return by_type
        text = f"{name} {(place.get('formattedAddress') or '')} {(place.get('editorialSummary') or {}).get('text', '')}".lower()
        free_keywords = ["免费", "free", "church", "cathedral", "park", "garden", "square", "bridge", "street", "beach"]
        expensive_keywords = ["museum", "castle", "tower", "palace", "eiffel", "louvre", "duomo", "sagrada", "disney", "amusement"]
        if any(k in text for k in free_keywords):
            return 0
        if any(k in text for k in expensive_keywords):
            return 20
        if place.get('rating') and float(place.get('rating') or 0) >= 4.6:
            return 12
        return 8

    def _estimate_stay_profile(self, query: str, name: str, place: Dict[str, Any]) -> tuple[int, str]:
        """建议停留（按“轻松自在”的默认节奏）：温泉/水疗 3.5 小时，博物馆/宫殿 2 小时，观景/桥/广场 30-45 分钟。"""
        from .pace import min_stay, is_spa, RELAXED
        ptype = str(place.get("primaryType") or "")
        text = f"{query} {name} {(place.get('formattedAddress') or '')} {(place.get('editorialSummary') or {}).get('text', '')}".lower()
        mins = min_stay(name, "", ptype, RELAXED)
        if is_spa(name, "", ptype) or (mins is None) or mins >= 100:
            if mins is None:
                mins = 60
            return mins, ("deep_visit" if mins >= 100 else "standard")
        citywalk_keywords = ["citywalk", "城市漫步", "步行", "街区", "街头", "河畔", "market"]
        if mins <= 45 or any(k in text for k in citywalk_keywords):
            return max(mins, 40), "citywalk_passby"
        return max(mins, 60), "standard"

    def _refresh_stay(self, query: str, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """缓存里的建议停留是旧规则算的：读出来时按当前（轻松节奏）规则重算，不必作废缓存、不多花 Google 费用。"""
        out: List[Dict[str, Any]] = []
        for idx, it in enumerate(items):
            if not isinstance(it, dict):
                out.append(it)
                continue
            mins, style = self._estimate_stay_profile(query, str(it.get("name") or ""), {
                "primaryType": it.get("primary_type") or "", "formattedAddress": it.get("formatted_address") or "",
                "editorialSummary": {"text": it.get("editorial_summary") or ""}})
            out.append({**it, "suggested_stay_minutes": mins, "visit_style": style,
                        "route_desc": f"第{idx + 1}站，建议停留约 {mins} 分钟（{style}）"})
        return out

    def _haversine_distance_meters(self, lat1: float, lng1: float, lat2: float, lng2: float) -> float:
        earth_radius_m = 6371000.0
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        delta_phi = math.radians(lat2 - lat1)
        delta_lambda = math.radians(lng2 - lng1)
        a = math.sin(delta_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return earth_radius_m * c

    def search_places(self, query: str, limit: int = 12) -> List[Dict[str, Any]]:
        if not self.settings.google_places_api_key:
            raise ValueError("GOOGLE_PLACES_API_KEY 未配置")

        url = f"{self.settings.google_places_base_url}/places:searchText"
        payload = {
            "textQuery": query,
            "languageCode": "zh-CN",
            "pageSize": max(5, min(limit, 20)),
        }
        cache_key = self._cache_key(query, limit)
        cached = self._read_cache(cache_key)
        if cached is not None:
            return self._refresh_stay(query, cached)
        headers = {
            "X-Goog-Api-Key": self.settings.google_places_api_key,
            "X-Goog-FieldMask": self.FIELD_MASK,
            "Content-Type": "application/json",
        }
        self._log("request", f"query={query}, limit={limit}, pageSize={payload['pageSize']}")
        if self.settings.debug:
            masked_key = f"{self.settings.google_places_api_key[:6]}***"
            log_key = self.settings.google_places_api_key if self.settings.debug_google_places_full_key else masked_key
            self._log("request_debug", f"url={url}, field_mask={self.FIELD_MASK}, api_key={log_key}")
            self._log("request_payload", json.dumps(payload, ensure_ascii=False))
            curl_headers = {
                "X-Goog-Api-Key": log_key,
                "X-Goog-FieldMask": self.FIELD_MASK,
                "Content-Type": "application/json",
            }
            self._log("request_curl", self._build_curl_command(url, curl_headers, payload))

        with httpx.Client(timeout=self.settings.google_places_timeout_seconds) as client:
            resp = client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            if self.settings.debug:
                self._log("response_status", f"http_status={resp.status_code}")
                self._log("response_body", json.dumps(data, ensure_ascii=False)[:5000])

        places = data.get("places", []) if isinstance(data, dict) else []

        normalized: List[Dict[str, Any]] = []
        places = [p for p in places if p.get("businessStatus") != "CLOSED_PERMANENTLY"]      # 已永久停业的不进候选
        for idx, p in enumerate(places[:limit]):
            loc = p.get("location") or {}
            place_name = (p.get("displayName") or {}).get("text", "未知景点")
            stay_minutes, visit_style = self._estimate_stay_profile(query, place_name, p)
            normalized.append(
                {
                    "name": place_name,
                    "lat": loc.get("latitude"),
                    "lng": loc.get("longitude"),
                    "formatted_address": p.get("formattedAddress", ""),
                    "rating": p.get("rating"),
                    "editorial_summary": (p.get("editorialSummary") or {}).get("text"),
                    "route_desc": f"第{idx + 1}站，建议停留约 {stay_minutes} 分钟（{visit_style}）",
                    "place_id": p.get("id") or p.get("name") or "",
                    "ticket_price": self._estimate_ticket_price(place_name, p),
                    "primary_type": p.get("primaryType") or "",
                    "hours": oh.compact(p.get("regularOpeningHours")),
                    "business_status": p.get("businessStatus") or "",
                    "suggested_stay_minutes": stay_minutes,
                    "visit_style": visit_style,
                }
            )
        if self.settings.debug:
            self._log("normalized", json.dumps(normalized[:10], ensure_ascii=False)[:4000])
        self._log("done", f"normalized_count={len(normalized)}")
        self._write_cache(cache_key, query, limit, normalized)

        return normalized

    def search_places_near_anchor(
        self,
        query: str,
        *,
        anchor_lat: float,
        anchor_lng: float,
        limit: int = 6,
        radius_meters: int = 2500,
    ) -> List[Dict[str, Any]]:
        search_limit = max(limit * 3, 8)
        items = self.search_places(query, limit=search_limit)
        enriched: List[Dict[str, Any]] = []
        for item in items:
            lat = item.get("lat")
            lng = item.get("lng")
            address = item.get("formatted_address") or item.get("address")
            if lat is None or lng is None or not address:
                continue
            try:
                distance_meters = self._haversine_distance_meters(float(anchor_lat), float(anchor_lng), float(lat), float(lng))
            except Exception:
                continue
            enriched.append(
                {
                    **item,
                    "address": address,
                    "latitude": lat,
                    "longitude": lng,
                    "distance_meters": int(distance_meters),
                }
            )
        if not enriched:
            self._log("nearby_search", f"query={query}, anchor=({anchor_lat},{anchor_lng}), no_geo_candidates")
            return []

        enriched.sort(key=lambda x: (x.get("distance_meters", 10**9), -(float(x.get("rating") or 0.0))))
        within_radius = [x for x in enriched if int(x.get("distance_meters") or 10**9) <= radius_meters]
        selected = within_radius[:limit] if within_radius else enriched[:limit]
        self._log(
            "nearby_search",
            f"query={query}, anchor=({anchor_lat},{anchor_lng}), radius={radius_meters}, "
            f"selected={len(selected)}, nearest={selected[0].get('distance_meters') if selected else 'n/a'}",
        )
        return selected


_google_places_service = None


def get_google_places_service() -> GooglePlacesService:
    global _google_places_service
    if _google_places_service is None:
        _google_places_service = GooglePlacesService()
    return _google_places_service
