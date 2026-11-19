"""行程数据处理的可复用纯函数（从 travel_plan.py 下沉）。

被多方共用，避免循环 import：旧流水线 `api/routes/travel_plan.py`、子 Agent `agents/subagents.py`、
`agents/composer.py`。这里只放**纯数据/归一化/兜底**逻辑；不 import 任何 service，故无循环依赖。
餐饮就近逻辑见 `meal_utils.py`。SSE/日志/prompt 仍留在 travel_plan.py。
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List

def _extract_json_object(text: str) -> Dict[str, Any]:
    s = (text or "").strip()
    if not s:
        return {}
    if "```json" in s:
        start = s.find("```json") + 7
        end = s.find("```", start)
        s = s[start:end].strip()
    elif "```" in s:
        start = s.find("```") + 3
        end = s.find("```", start)
        s = s[start:end].strip()
    if "{" in s and "}" in s:
        s = s[s.find("{") : s.rfind("}") + 1]
    try:
        obj = json.loads(s)
        return obj if isinstance(obj, dict) else {}
    except Exception: 
        return {}


def _normalize_attractions(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    for item in items:
        normalized.append(
            {
                "name": item.get("name", ""),
                "lat": item.get("lat"),
                "lng": item.get("lng"),
                "formatted_address": item.get("formatted_address", ""),
                "rating": item.get("rating"),
                "route_desc": item.get("route_desc", ""),
                "place_id": item.get("place_id", ""),
                "ticket_price": item.get("ticket_price", 0),
                "primary_type": item.get("primary_type", ""),
                "editorial_summary": item.get("editorial_summary"),
                "suggested_stay_minutes": item.get("suggested_stay_minutes"),
                "visit_style": item.get("visit_style", "standard"),
                **{k:item[k] for k in ('experience_category','source_url','seasonality_note','experience_priority') if item.get(k)},
                **({"hours": item["hours"]} if item.get("hours") else {}),
                **({"must_include": True} if item.get("must_include") else {}),
            }
        )
    return normalized


def _compact_attractions_for_llm(items: List[Dict[str, Any]], max_items: int = 10) -> List[Dict[str, Any]]:
    compact: List[Dict[str, Any]] = []
    for item in items[:max_items]:
        compact.append(
            {
                "name": item.get("name", ""),
                "lat": item.get("lat"),
                "lng": item.get("lng"),
                "formatted_address": item.get("formatted_address", ""),
                "rating": item.get("rating"),
                "ticket_price": item.get("ticket_price", 0),
                "place_id": item.get("place_id", ""),
                "suggested_stay_minutes": item.get("suggested_stay_minutes"),
                "visit_style": item.get("visit_style", "standard"),
                **{k:item[k] for k in ('experience_category','source_url','seasonality_note','experience_priority') if item.get(k)},
                **({"must_include": True} if item.get("must_include") else {}),
            }
        )
    return compact


def _compact_meals_for_llm(items: List[Dict[str, Any]], max_items: int = 9) -> List[Dict[str, Any]]:
    compact: List[Dict[str, Any]] = []
    for item in items[:max_items]:
        compact.append(
            {
                "type": item.get("type", "snack"),
                "name": item.get("name", ""),
                "time": item.get("time", ""),
                "description": item.get("description", ""),
                "route_desc": item.get("route_desc", ""),
                "estimated_cost": item.get("estimated_cost", 0),
                "address": item.get("address", ""),
                "latitude": item.get("latitude"),
                "longitude": item.get("longitude"),
                "place_id": item.get("place_id", ""),
            }
        )
    return compact


def _dedupe_by_name(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen: set[str] = set()
    deduped: List[Dict[str, Any]] = []
    for item in items:
        name = str(item.get("name") or "").strip().lower()
        if not name or name in seen:
            continue
        seen.add(name)
        deduped.append(item)
    return deduped


def _build_fallback_day_plan(day_index: int, theme: str, theme_tags: List[str], attractions: List[Dict[str, Any]], meals: List[Dict[str, Any]]) -> Dict[str, Any]:
    title = f"Day {day_index + 1} · {theme or '主题游览'}"
    route_summary = f"围绕{theme or '当天主题'}灵活安排行程，优先使用现有候选池中的景点与餐饮。"
    activities: List[Dict[str, Any]] = []
    for idx, attr in enumerate(attractions[:4], start=1):
        activities.append(
            {
                "name": attr.get("name", f"景点{idx}"),
                "time": f"{9 + idx - 1:02d}:00-{10 + idx - 1:02d}:00",
                "description": attr.get("description") or f"符合{theme or '当天'}主题的候选景点。",
                "route_desc": attr.get("route_desc") or "根据景点位置顺序游览，注意控制步行距离。",
                "estimated_cost": 0,
                "ticket_price": int(attr.get("ticket_price") or 0),
                "address": attr.get("formatted_address") or "",
                "latitude": attr.get("lat"),
                "longitude": attr.get("lng"),
            }
        )
    if not activities:
        activities.append(
            {
                "name": "自由活动",
                "time": "09:00-11:00",
                "description": f"当前候选池不足，围绕{theme or '当天主题'}进行弹性安排。",
                "route_desc": "按当天主题就近安排，抵达后可结合现场情况灵活调整。",
                "estimated_cost": 0,
                "ticket_price": 0,
                "address": "",
                "latitude": None,
                "longitude": None,
            }
        )
    day_meals: List[Dict[str, Any]] = []
    meal_slots = ["breakfast", "lunch", "dinner"]
    for idx, meal_type in enumerate(meal_slots):
        meal = meals[idx] if idx < len(meals) else {}
        day_meals.append(
            {
                "type": meal_type,
                "name": meal.get("name", f"{meal_type} 安排"),
                "time": meal.get("time") or ("08:00-08:40" if meal_type == "breakfast" else "12:00-13:00" if meal_type == "lunch" else "18:00-19:00"),
                "description": meal.get("description") or f"根据{theme or '当天主题'}选择的餐饮。",
                "route_desc": meal.get("route_desc") or "结合当天路线就近安排。",
                "estimated_cost": int(meal.get("estimated_cost") or 0),
                "address": meal.get("address") or "",
                "latitude": meal.get("latitude"),
                "longitude": meal.get("longitude"),
                "place_id": meal.get("place_id") or "",
            }
        )
    return {
        "day": day_index + 1,
        "title": title,
        "route_summary": route_summary,
        "activities": activities,
        "meals": day_meals,
        "theme_tags": theme_tags,
    }


def _build_fallback_plan(location: str, days: int, daily_buckets: List[Dict[str, Any]], attractions: List[Dict[str, Any]], meal_candidates: List[Dict[str, Any]], warnings: List[str]) -> Dict[str, Any]:
    deduped_attractions = _dedupe_by_name(attractions)
    deduped_meals = _dedupe_by_name(meal_candidates)
    itinerary: List[Dict[str, Any]] = []
    for idx in range(days):
        bucket = daily_buckets[idx] if idx < len(daily_buckets) and isinstance(daily_buckets[idx], dict) else {}
        theme = str(bucket.get("theme") or f"Day {idx + 1}")
        theme_tags = _ensure_list(bucket.get("theme_tags"))
        bucket_attractions = _dedupe_by_name(_ensure_list(bucket.get("attractions")))
        bucket_meals = _dedupe_by_name(_ensure_list(bucket.get("meals")))
        if not bucket_attractions:
            start = idx * 3
            bucket_attractions = deduped_attractions[start : start + 3]
        if not bucket_meals:
            start = idx * 3
            bucket_meals = deduped_meals[start : start + 3]
        itinerary.append(_build_fallback_day_plan(idx, theme, theme_tags, bucket_attractions, bucket_meals))
    total_attractions = sum(int(item.get("ticket_price") or 0) for item in deduped_attractions[: max(days * 3, 1)])
    total_meals = sum(int(item.get("estimated_cost") or 0) for item in deduped_meals[: max(days * 3, 1)])
    total_transport = max(days * 10, 0)
    return {
        "location": location,
        "days": days,
        "total_budget": {
            "transport": total_transport,
            "tickets": total_attractions,
            "food": total_meals,
            "total": total_attractions + total_meals + total_transport,
            "currency": "EUR",
        },
        "itinerary": itinerary,
        "tips": ["行程已按路线顺畅优先编排，如需更多选择，可对任意一站点击调整。"],
        "warnings": warnings or ["部分日期已优先保证路线顺畅，可点“调整这一站”增加更多去处。"],
    }


def _calc_candidate_limit(days: int) -> int:
    return days * 8


def _normalize_day_title(day_no: int, title: str, route_summary: str) -> str:
    raw_title = str(title or "").strip()
    raw_summary = str(route_summary or "").strip()
    banned_patterns = [
        r"梦幻",
        r"史诗",
        r"炸裂",
        r"封神",
        r"神级",
        r"必打卡",
        r"超值",
        r"顶级",
        r"完美",
        r"极致",
    ]
    cleaned = raw_title
    for pattern in banned_patterns:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"[!！]{1,}", "", cleaned).strip(" -|·，,")

    if not cleaned:
        summary_brief = raw_summary.split("，")[0].split("。")[0].strip()
        if summary_brief:
            return f"Day {day_no}｜{summary_brief}"
        return f"Day {day_no}｜区域步行与主题游览"

    # 统一成 “Day N｜主题”：先去掉旧式前缀（第N天 / Day N），再按当天序号重新加
    cleaned = re.sub(r"^\s*(?:第\s*\d+\s*天|Day\s*\d+)\s*[｜|·:：\-]?\s*", "", cleaned, flags=re.IGNORECASE).strip()
    cleaned = f"Day {day_no}｜{cleaned}" if cleaned else f"Day {day_no}｜区域步行与主题游览"
    return cleaned


def _is_citywalk_preference(preferences: str) -> bool:
    text = (preferences or "").lower()
    citywalk_keywords = ["citywalk", "城市漫步", "city walk", "walk", "步行", "走马观花", "逛街", "街区"]
    return any(k in text for k in citywalk_keywords)


def _ensure_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []



def _build_theme_fallbacks(location: str, day: int, theme: str, theme_tags: List[str], preferences: str) -> tuple[List[str], List[str]]:
    tags = [str(t).strip() for t in theme_tags if str(t).strip()]
    search_preferences=re.sub(r'\[experience:.*?\[/experience\]','',preferences,flags=re.S).split('；交通约束：',1)[0].strip()
    pref_tags = [p.strip() for p in search_preferences.replace("；", ",").replace("/", ",").split(",") if p.strip()]
    seeds = tags[:3] or pref_tags[:2] or [theme or "当地特色体验与代表性景点"]
    attraction_queries: List[str] = []
    if theme:
        attraction_queries.extend([
            f"{location} {theme} 景点",
            f"{location} {theme} 地标",
            f"{location} {theme} 必去",
        ])
    for seed in seeds:
        attraction_queries.append(f"{location} {seed} 景点")
        attraction_queries.append(f"{location} {seed} 地标")
    attraction_queries.extend([
        f"{location} 代表性景点",
        f"{location} 当地市集 手作体验 现场演出",
        f"{location} 城市地标",
    ])
    meal_queries = [f"{location} {seed} 餐厅" for seed in seeds[:2]]
    meal_queries.extend([f"{location} 当地美食", f"{location} 特色餐厅", f"{location} 市中心餐厅"])
    return attraction_queries[:6], meal_queries[:4]



# ── schema 必填字段兜底（spec003 踩过 LLM 返回 description=null 直接崩 TravelPlanData 的坑）──

def coerce_activity(act: Dict[str, Any]) -> Dict[str, Any]:
    """把 LLM 产出的单个 activity 补成 TravelPlanActivity 必填齐全（string/float 不为 None）。"""
    return {
        **act,
        "name": str(act.get("name") or ""),
        "time": str(act.get("time") or ""),
        "description": str(act.get("description") or ""),
        "route_desc": str(act.get("route_desc") or ""),
        "estimated_cost": float(act.get("estimated_cost") or 0),
        "ticket_price": float(act.get("ticket_price") or 0),
        "preference_matched": bool(act.get("preference_matched")),
        "preference_reason": str(act.get("preference_reason") or ""),
    }


def coerce_meal(meal: Dict[str, Any]) -> Dict[str, Any]:
    """把 LLM 产出的单个 meal 补成 TravelPlanMeal 必填齐全。"""
    return {
        **meal,
        "type": str(meal.get("type") or "snack"),
        "name": str(meal.get("name") or ""),
        "time": str(meal.get("time") or ""),
        "description": str(meal.get("description") or ""),
        "route_desc": str(meal.get("route_desc") or ""),
        "estimated_cost": float(meal.get("estimated_cost") or 0),
    }


def coerce_day(day: Dict[str, Any], day_no: int) -> Dict[str, Any]:
    """把 LLM 产出的单天补成 TravelPlanDay 必填齐全。"""
    activities = [coerce_activity(a) for a in _ensure_list(day.get("activities")) if isinstance(a, dict)]
    meals = [coerce_meal(m) for m in _ensure_list(day.get("meals")) if isinstance(m, dict)]
    return {
        **day,
        "day": int(day.get("day") or day_no),
        "title": _normalize_day_title(day_no, str(day.get("title") or ""), str(day.get("route_summary") or "")),
        "route_summary": str(day.get("route_summary") or ""),
        "activities": activities,
        "meals": meals,
    }
