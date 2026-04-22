"""Google Places API (New) 服务封装"""

import hashlib
import json
import math
import time
from pathlib import Path
from typing import Any, Dict, List

import httpx

from ..config import get_settings


class GooglePlacesService:
    """Google Places API(New) 服务"""

    FIELD_MASK = "places.displayName,places.location,places.formattedAddress,places.rating,places.editorialSummary"
    CACHE_TTL_SECONDS = 7 * 24 * 60 * 60

    def __init__(self):
        self.settings = get_settings()
        self.cache_dir = Path(__file__).resolve().parents[2] / "cache" / "google_places"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _log(self, stage: str, msg: str) -> None:
        ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        print(f"{ts} [google-places][{stage}] {msg}")

    def _cache_key(self, query: str, limit: int) -> str:
        raw = json.dumps({"query": query.strip().lower(), "limit": limit, "field_mask": self.FIELD_MASK}, ensure_ascii=False, sort_keys=True)
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

    def _estimate_ticket_price(self, name: str, place: Dict[str, Any]) -> float:
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
        text = f"{query} {name} {(place.get('formattedAddress') or '')} {(place.get('editorialSummary') or {}).get('text', '')}".lower()
        citywalk_keywords = ["citywalk", "城市漫步", "walk", "步行", "走马观花", "街区", "街头", "河畔", "桥", "广场", "market"]
        deep_visit_keywords = ["museum", "博物馆", "美术馆", "gallery", "palace", "castle", "宫殿", "城堡", "basilica", "cathedral", "教堂", "温泉", "bath"]
        quick_spot_keywords = ["viewpoint", "观景", "桥", "桥梁", "street", "步行街", "square", "喷泉", "雕像", "纪念碑"]

        if any(k in text for k in deep_visit_keywords):
            return 90, "deep_visit"
        if any(k in text for k in citywalk_keywords) or any(k in text for k in quick_spot_keywords):
            return 35, "citywalk_passby"
        return 60, "standard"

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
            return cached
        headers = {
            "X-Goog-Api-Key": self.settings.google_places_api_key,
            "X-Goog-FieldMask": self.FIELD_MASK,
            "Content-Type": "application/json",
        }
        masked_key = f"{self.settings.google_places_api_key[:6]}***"
        log_key = self.settings.google_places_api_key if self.settings.debug_google_places_full_key else masked_key
        self._log(
            "request",
            f"url={url}, query={query}, limit={limit}, pageSize={payload['pageSize']}, "
            f"field_mask={self.FIELD_MASK}, api_key={log_key}",
        )
        self._log("request_payload", json.dumps(payload, ensure_ascii=False))
        curl_headers = {
            "X-Goog-Api-Key": log_key,
            "X-Goog-FieldMask": self.FIELD_MASK,
            "Content-Type": "application/json",
        }
        self._log("request_curl", self._build_curl_command(url, curl_headers, payload))

        with httpx.Client(timeout=self.settings.google_places_timeout_seconds) as client:
            resp = client.post(url, json=payload, headers=headers)
            self._log("response_status", f"http_status={resp.status_code}")
            self._log("response_headers", f"content_type={resp.headers.get('content-type', '')}")
            resp.raise_for_status()
            data = resp.json()
            raw_preview = json.dumps(data, ensure_ascii=False)[:5000]
            self._log("response_body", raw_preview)

        places = data.get("places", []) if isinstance(data, dict) else []
        self._log("response_parse", f"places_count={len(places)}")

        normalized: List[Dict[str, Any]] = []
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
                    "suggested_stay_minutes": stay_minutes,
                    "visit_style": visit_style,
                }
            )
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
