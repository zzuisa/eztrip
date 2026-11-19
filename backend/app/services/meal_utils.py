"""餐饮候选的检索/就近校验逻辑（从 travel_plan.py 下沉）。

`service` 由调用方传入（Google Places），不在此 import service，故无循环依赖。
依赖 `itinerary_utils._ensure_list`（单向）。
"""

from __future__ import annotations

import math
from typing import Any, Dict, List

from .itinerary_utils import _ensure_list

MEAL_SLOT_POLICY: Dict[str, Dict[str, int]] = {
    "breakfast": {"radius_meters": 1200, "max_distance_meters": 3000, "limit": 4},
    "lunch": {"radius_meters": 1800, "max_distance_meters": 3500, "limit": 5},
    "dinner": {"radius_meters": 2600, "max_distance_meters": 4500, "limit": 5},
}


def _is_valid_geo(lat: Any, lng: Any) -> bool:
    return lat is not None and lng is not None


def _distance_meters(lat1: float, lng1: float, lat2: float, lng2: float) -> int:
    earth_radius_m = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lng2 - lng1)
    a = math.sin(delta_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return int(earth_radius_m * c)


def _extract_day_meal_anchors(day_attractions: List[Dict[str, Any]]) -> Dict[str, Dict[str, float]]:
    points = []
    for item in day_attractions:
        lat = item.get("lat")
        lng = item.get("lng")
        if _is_valid_geo(lat, lng):
            points.append({"lat": float(lat), "lng": float(lng)})
    if not points:
        return {}
    first = points[0]
    middle = points[len(points) // 2]
    last = points[-1]
    centroid = {
        "lat": sum(p["lat"] for p in points) / len(points),
        "lng": sum(p["lng"] for p in points) / len(points),
    }
    return {
        "breakfast": first,
        "lunch": middle,
        "dinner": last,
        "fallback": centroid,
    }


def _normalize_meal_candidate(item: Dict[str, Any], meal_type: str = "snack") -> Dict[str, Any] | None:
    address = item.get("address") or item.get("formatted_address") or ""
    latitude = item.get("latitude") if item.get("latitude") is not None else item.get("lat")
    longitude = item.get("longitude") if item.get("longitude") is not None else item.get("lng")
    if not address or not _is_valid_geo(latitude, longitude):
        return None
    rating = float(item.get("rating") or 0.0)
    estimated_cost = int(item.get("estimated_cost") or (10 if rating < 4.0 else 16 if rating < 4.5 else 22))
    return {
        "type": meal_type,
        "name": str(item.get("name") or "").strip(),
        "time": item.get("time", ""),
        "description": item.get("description") or item.get("editorial_summary") or "",
        "route_desc": item.get("route_desc") or "",
        "estimated_cost": estimated_cost,
        "address": address,
        "latitude": float(latitude),
        "longitude": float(longitude),
        "place_id": item.get("place_id") or "",
        "rating": item.get("rating"),
        "distance_meters": int(item.get("distance_meters") or 0),
    }


def _dedupe_meals(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen: set[str] = set()
    deduped: List[Dict[str, Any]] = []
    for item in items:
        key = str(item.get("place_id") or "").strip() or str(item.get("name") or "").strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _derive_meal_slot_queries(location: str, meal_queries: List[Any], meal_type: str) -> List[str]:
    base = [str(q).strip() for q in meal_queries if str(q).strip()]
    slot_terms = {
        "breakfast": ["早餐", "早午餐", "咖啡馆"],
        "lunch": ["午餐", "本地餐厅", "简餐"],
        "dinner": ["晚餐", "特色餐厅", "评价高餐厅"],
    }
    terms = slot_terms.get(meal_type, ["餐厅"])
    queries = [f"{location} {term}" for term in terms]
    queries.extend(base[:2])
    return list(dict.fromkeys(queries))


def _collect_meals_near_anchors(
    service: Any,
    *,
    location: str,
    day_index: int,
    meal_queries: List[Any],
    day_attractions: List[Dict[str, Any]],
) -> tuple[List[Dict[str, Any]], Dict[str, Any], Dict[str, int]]:
    anchors = _extract_day_meal_anchors(day_attractions)
    by_type: Dict[str, List[Dict[str, Any]]] = {"breakfast": [], "lunch": [], "dinner": []}
    stats = {"total": 0, "geo_valid": 0, "address_valid": 0}
    if not anchors:
        fallback_items: List[Dict[str, Any]] = []
        for query in [str(q).strip() for q in meal_queries if str(q).strip()][:3]:
            raw_items = service.search_places(query, limit=6)
            stats["total"] += len(raw_items)
            for raw_item in raw_items:
                normalized = _normalize_meal_candidate(raw_item, meal_type="snack")
                if not normalized:
                    continue
                stats["geo_valid"] += 1
                stats["address_valid"] += 1
                fallback_items.append(normalized)
        merged_fallback = _dedupe_meals(fallback_items)
        return merged_fallback, {"anchors": {}, "by_type": by_type, "all": merged_fallback}, stats

    for meal_type in ("breakfast", "lunch", "dinner"):
        policy = MEAL_SLOT_POLICY[meal_type]
        anchor = anchors.get(meal_type) or anchors.get("fallback")
        if not anchor:
            continue
        slot_queries = _derive_meal_slot_queries(location, meal_queries, meal_type)
        slot_candidates: List[Dict[str, Any]] = []
        for query in slot_queries[:3]:
            nearby = service.search_places_near_anchor(
                query,
                anchor_lat=float(anchor["lat"]),
                anchor_lng=float(anchor["lng"]),
                limit=max(2, policy["limit"]),
                radius_meters=policy["radius_meters"],
            )
            stats["total"] += len(nearby)
            for raw_item in nearby:
                normalized = _normalize_meal_candidate(raw_item, meal_type=meal_type)
                if not normalized:
                    continue
                stats["geo_valid"] += 1
                if normalized.get("address"):
                    stats["address_valid"] += 1
                distance = normalized.get("distance_meters") or _distance_meters(
                    float(anchor["lat"]), float(anchor["lng"]), float(normalized["latitude"]), float(normalized["longitude"])
                )
                normalized["distance_meters"] = distance
                if int(distance) <= int(policy["max_distance_meters"]):
                    slot_candidates.append(normalized)
        by_type[meal_type] = _dedupe_meals(slot_candidates)[: policy["limit"]]

    merged = _dedupe_meals(by_type["breakfast"] + by_type["lunch"] + by_type["dinner"])
    return merged, {"anchors": anchors, "by_type": by_type, "all": merged}, stats


def _get_anchor_for_meal(day_source: Dict[str, Any], meal_type: str) -> Dict[str, float] | None:
    anchors = day_source.get("anchors") if isinstance(day_source, dict) else {}
    if not isinstance(anchors, dict):
        return None
    return anchors.get(meal_type) or anchors.get("fallback")


def _meal_has_required_fields(meal: Dict[str, Any]) -> bool:
    return bool(meal.get("address")) and _is_valid_geo(meal.get("latitude"), meal.get("longitude"))


def _pick_nearest_meal_candidate(
    candidates: List[Dict[str, Any]],
    *,
    anchor: Dict[str, float] | None,
    max_distance_meters: int,
) -> Dict[str, Any] | None:
    if not candidates:
        return None
    if not anchor:
        return candidates[0]
    nearest: Dict[str, Any] | None = None
    nearest_distance = 10**9
    for item in candidates:
        if not _meal_has_required_fields(item):
            continue
        distance = item.get("distance_meters")
        if distance is None:
            distance = _distance_meters(float(anchor["lat"]), float(anchor["lng"]), float(item["latitude"]), float(item["longitude"]))
        if int(distance) <= max_distance_meters and int(distance) < nearest_distance:
            nearest = {**item, "distance_meters": int(distance)}
            nearest_distance = int(distance)
    return nearest


def _enforce_meal_quality_on_itinerary(
    *,
    service: Any,
    location: str,
    itinerary: List[Dict[str, Any]],
    daily_meal_sources: Dict[int, Dict[str, Any]],
) -> tuple[List[Dict[str, Any]], Dict[str, int]]:
    metrics = {
        "meal_selected_within_radius": 0,
        "meal_missing_geo": 0,
        "meal_missing_address": 0,
    }
    fixed_itinerary: List[Dict[str, Any]] = []
    for day in itinerary:
        if not isinstance(day, dict):
            continue
        day_no = int(day.get("day") or len(fixed_itinerary) + 1)
        source = daily_meal_sources.get(day_no, {})
        by_type = source.get("by_type", {}) if isinstance(source, dict) else {}
        meals_fixed: List[Dict[str, Any]] = []
        for meal in _ensure_list(day.get("meals")):
            if not isinstance(meal, dict):
                continue
            meal_type = str(meal.get("type") or "snack")
            policy = MEAL_SLOT_POLICY.get(meal_type, MEAL_SLOT_POLICY["lunch"])
            anchor = _get_anchor_for_meal(source, meal_type)
            candidates = _ensure_list(by_type.get(meal_type)) + _ensure_list(source.get("all"))

            if not _meal_has_required_fields(meal):
                nearest = _pick_nearest_meal_candidate(candidates, anchor=anchor, max_distance_meters=policy["max_distance_meters"])
                if not nearest and anchor:
                    rescue_query = f"{location} {meal.get('name') or ''} {meal_type} 餐厅".strip()
                    rescue = service.search_places_near_anchor(
                        rescue_query,
                        anchor_lat=float(anchor["lat"]),
                        anchor_lng=float(anchor["lng"]),
                        limit=1,
                        radius_meters=policy["max_distance_meters"],
                    )
                    if rescue:
                        nearest = _normalize_meal_candidate(rescue[0], meal_type=meal_type)
                if nearest:
                    meal = {
                        **meal,
                        "address": meal.get("address") or nearest.get("address"),
                        "latitude": meal.get("latitude") if meal.get("latitude") is not None else nearest.get("latitude"),
                        "longitude": meal.get("longitude") if meal.get("longitude") is not None else nearest.get("longitude"),
                        "place_id": meal.get("place_id") or nearest.get("place_id"),
                        "estimated_cost": meal.get("estimated_cost") or nearest.get("estimated_cost") or 0,
                    }

            if not _is_valid_geo(meal.get("latitude"), meal.get("longitude")):
                metrics["meal_missing_geo"] += 1
            if not meal.get("address"):
                metrics["meal_missing_address"] += 1

            if anchor and _is_valid_geo(meal.get("latitude"), meal.get("longitude")):
                distance = _distance_meters(float(anchor["lat"]), float(anchor["lng"]), float(meal["latitude"]), float(meal["longitude"]))
                meal["distance_meters"] = distance
                if distance <= int(policy["max_distance_meters"]):
                    metrics["meal_selected_within_radius"] += 1
            meals_fixed.append(meal)
        fixed_itinerary.append({**day, "meals": meals_fixed})
    return fixed_itinerary, metrics

