"""Google Places API (New) 服务封装"""

import json
from typing import Any, Dict, List

import httpx

from ..config import get_settings


class GooglePlacesService:
    """Google Places API(New) 服务"""

    FIELD_MASK = "places.displayName,places.location,places.formattedAddress,places.rating,places.editorialSummary"

    def __init__(self):
        self.settings = get_settings()

    def _log(self, stage: str, msg: str) -> None:
        print(f"[google-places][{stage}] {msg}")

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

    def search_places(self, query: str, limit: int = 12) -> List[Dict[str, Any]]:
        if not self.settings.google_places_api_key:
            raise ValueError("GOOGLE_PLACES_API_KEY 未配置")

        url = f"{self.settings.google_places_base_url}/places:searchText"
        payload = {
            "textQuery": query,
            "languageCode": "zh-CN",
            "pageSize": max(5, min(limit, 20)),
        }
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
            normalized.append(
                {
                    "name": (p.get("displayName") or {}).get("text", "未知景点"),
                    "lat": loc.get("latitude"),
                    "lng": loc.get("longitude"),
                    "formatted_address": p.get("formattedAddress", ""),
                    "rating": p.get("rating"),
                    "editorial_summary": (p.get("editorialSummary") or {}).get("text"),
                    "route_desc": f"第{idx + 1}站，建议停留 1-2 小时",
                    "place_id": p.get("id") or p.get("name") or "",
                    "ticket_price": self._estimate_ticket_price((p.get("displayName") or {}).get("text", ""), p),
                }
            )
        self._log("normalized", json.dumps(normalized[:10], ensure_ascii=False)[:4000])
        self._log("done", f"normalized_count={len(normalized)}")

        return normalized


_google_places_service = None


def get_google_places_service() -> GooglePlacesService:
    global _google_places_service
    if _google_places_service is None:
        _google_places_service = GooglePlacesService()
    return _google_places_service
