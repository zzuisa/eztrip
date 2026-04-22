"""RogueTrip Google Places 旅行规划 API（LLM 直出 JSON）"""

from __future__ import annotations

import json
import math
import time
from textwrap import dedent
from typing import Any, Dict, List
import re

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse

from ...config import get_settings
from ...models.schemas import TravelPlanRequest, TravelPlanResponseV2, TravelPlanData
from ...services.google_places_service import get_google_places_service
from ...services.llm_service import get_llm_router
from ...services.travel_plan_store import get_travel_plan_store

router = APIRouter(prefix="/travel-plan", tags=["旅行规划"])

SYSTEM_PROMPT = """你是一位极度严谨、拥有强大空间规划和多国行程设计能力的欧洲旅行规划专家。
核心规则：
- 严格使用用户提供的 Google Places API 返回的景点数据，不得自行添加或删除景点。
- 所有空间分组、路线排序、交通方式选择、时间安排、预算分配等复杂规划任务，全部由你独立完成。
- 输出必须是纯 JSON，不允许任何额外文字。
- 当前日期：2026-04-13"""

TRAVEL_PLAN_SCHEMA_EXAMPLE = {
    "location": "string",
    "days": 1,
    "total_budget": {
        "transport": 0,
        "tickets": 0,
        "food": 0,
        "total": 0,
        "currency": "EUR",
    },
    "itinerary": [
        {
            "day": 1,
            "title": "string",
            "route_summary": "string",
            "activities": [
                {
                    "name": "string",
                    "time": "09:00-11:00",
                    "description": "string",
                    "route_desc": "string（包含真实交通方式和预计时间）",
                    "estimated_cost": 0,
                    "ticket_price": 0,
                    "address": "string",
                    "latitude": 0,
                    "longitude": 0,
                    "preference_matched": False,
                    "preference_reason": "string",
                }
            ],
            "meals": [
                {
                    "type": "breakfast",
                    "name": "string",
                    "time": "08:00-08:40",
                    "description": "string",
                    "route_desc": "string（包含真实交通方式和预计时间）",
                    "estimated_cost": 0,
                    "address": "string",
                    "latitude": 0,
                    "longitude": 0,
                    "place_id": "string",
                }
            ],
        }
    ],
    "tips": ["string"],
    "warnings": ["string"],
}

SEARCH_STRATEGY_PROMPT = dedent(
    """
    你是专业的旅行规划搜索策略专家，擅长为 Google Places API 设计高效、精准的检索策略。

    根据以下用户输入，先生成一份“按天主题拆分 + 每日检索计划”的结构化搜索策略：

    用户输入地点：{location}
    旅行天数：{days} 天
    用户偏好：{preferences}

    请严格按照以下要求思考，然后**只输出一个合法的 JSON 对象，不要输出任何其他文字、解释或 markdown**。

    JSON 结构必须完全符合以下格式：
    {{
      "focus_tags": ["标签A", "标签B", ...],
      "pace": "relaxed" | "standard" | "deep",
      "budget_level": "low" | "mid" | "high",
      "must_include": ["必选项A", "必选项B", ...],
      "avoid": ["排除项A", "排除项B", ...],
      "daily_themes": [
        {{
          "day": 1,
          "theme": "网红打卡点",
          "theme_tags": ["landmark", "instagrammable"],
          "attraction_queries": ["query1", "query2", ...],
          "meal_queries": ["query1", "query2", ...]
        }},
        {{
          "day": 2,
          "theme": "城市漫步",
          "theme_tags": ["citywalk", "street", "cafe"],
          "attraction_queries": ["query1", "query2", ...],
          "meal_queries": ["query1", "query2", ...]
        }}
      ]
    }}

    生成规则（必须严格遵守）：
    - daily_themes 的长度必须等于 {days}，按天顺序输出。
    - 默认每天主题应优先采用高命中率、通用性强的方向，如“网红打卡点”“城市漫步”“经典地标”“河畔观景”“老城风情”等，除非用户偏好明确要求小众主题。
    - 每一天都要有一个清晰的主题，并围绕该主题生成该天的 attraction_queries / meal_queries。
    - 每天的 attraction_queries 建议 2-4 条；每天的 meal_queries 建议 2-3 条。
    - focus_tags 3-6 个，代表整个行程的核心偏好。
    - theme_tags 用于该天的局部主题标签，必须与当天主题一致。
    - pace：根据用户偏好和天数判断（relaxed=轻松休闲、standard=均衡、deep=深度体验）。
    - budget_level：根据用户偏好推断（low=经济型、mid=舒适型、high=高端体验），无明确预算时默认 mid。
    - must_include：用户明显提到的必去类型或偏好（没有则为空数组 []）。
    - avoid：仅当用户明确表达排斥时填写，否则必须为空数组 []。
    - 偏好要“优先但不过载”：即使用户有强偏好，也要保留合理多样性，避免每天所有景点/所有餐饮都集中在单一类型。
    - 对 2 天行程：单一主题景点建议不超过当天景点的约 60%-70%；单一菜系餐饮建议不超过当天餐饮的约 60%-70%。

    思考原则（仅在内部思考，不要输出）：
    1. 先根据天数拆分每日主题，再为每一天设计局部检索任务。
    2. 同一天的查询应围绕同一个主题和地理区域展开。
    3. 避免把所有查询都做成泛化模板。
    4. 优先让每日主题与用户偏好强相关。

    输出要求：
    - 必须是合法、可直接被 json.loads 解析的 JSON。
    - 所有数组不能为空（除 must_include 和 avoid 在无内容时可为空）。
    - 语言与用户输入保持一致（中文优先）。
    """
).strip()

TRAVEL_PLAN_PROMPT_TEMPLATE = dedent(
    """
    任务背景
    - 用户输入地点：{location}
    - 天数：{days} 天
    - 用户偏好（必须优先满足，作为关键规划约束）：{preferences}
    - 检索策略重点：{search_strategy}
    - 按天候选池：{daily_buckets_json}

    关键规划规则
    1. 用户偏好要优先注入到每天的景点筛选、路线排序、餐饮选择、停留时长、预算分配中。
    2. 如果偏好提到博物馆、艺术、历史、自然、购物、美食、亲子、夜生活等，请在 itinerary 的标题、route_summary、activities、meals 中明确体现。
    3. 每天至少安排 3–5 个景点，并包含早餐、午餐、晚餐；餐饮优先选择与偏好一致、且靠近当天景点路径的地点。
    4. 对于偏好相关的景点，请放入当天最重要的位置，并在 description / route_desc 中明确说明“为什么与偏好一致”。
    5. 如果用户偏好是预算、节奏、深度游、轻松游等，请把它体现在时间安排与 estimated_cost 中。
    6. 票价、地址、经纬度都要保留真实数据；无门票则 ticket_price=0。
    7. 所有景点的 `route_desc` 必须写成真实、具体、可执行的停留安排，禁止使用模板化的“第x站，建议停留 1-2 小时”。
    8. 每个景点的停留时间应根据景点属性、用户偏好和当天节奏动态安排，常见范围为 45 分钟到 3 小时，博物馆/深度参观可更长，轻量观景/拍照可更短。
    9. `time` 和 `route_desc` 需要与周边景点、餐饮和交通顺序一致，避免所有景点都写成相同停留时长。
    10. 若偏好或主题包含 citywalk/城市漫步/走马观花，请优先采用“短停留多点位”策略：每天优先安排 5–8 个可步行串联的小景点；单点停留通常 20–50 分钟，地标核心点可 50–80 分钟。
    11. 你会收到候选池中的 `suggested_stay_minutes` 与 `visit_style` 字段，必须把它们作为时间安排基线，再结合交通和餐饮窗口微调。
    12. 每天的标题 `title` 要克制、信息化，避免夸张或营销语气；标题应让用户一眼看出“当天为何这样安排（区域/主题/节奏）”。
    13. 餐饮只能从通过“就近距离+地址完整+经纬度完整”校验的候选池中选择；禁止输出缺失地址或坐标的餐馆。
    14. 偏好满足需遵循“高相关 + 多样性平衡”：不能把同一偏好类型机械铺满全部时段（例如全程都去动物园、每一餐都同一菜系）。
    15. 若用户偏好是“喜欢某类内容”，优先将其安排在关键时段或核心点位，同时保留至少 30%-40% 的互补体验（城市地标、街区漫步、本地经典、不同菜系等）。
    16. 对于因用户偏好而优先安排的景点活动，必须显式标记 `preference_matched=true`，并在 `preference_reason` 中用一句话说明匹配原因；非偏好驱动活动标记为 `false`。

    以下是 Google Places API 返回的真实景点数据（请严格使用这些数据）：
    {attractions_json}

    以下是餐饮候选数据（同样来自 Google Places，请就近搭配）：
    {meals_json}

    请充分发挥你的规划能力，完成以下任务：
    - 对景点进行合理的空间分组和路线规划（考虑真实交通逻辑）
    - 生成一份连贯、可执行的 {days} 天旅行计划
    - 每天安排 3–5 个景点，并包含早餐、午餐、晚餐
    - 若检测到 citywalk/城市漫步偏好，允许每天安排 5–8 个景点，但必须保持时间链路可执行
    - 餐饮也请使用 Google Places 风格的位置数据输出，且尽量在景点附近或路线上
    - 展示每个景点的门票价格；如无门票则明确写 0
    - 计算现实的每日和总预算（中档标准）
    - 为每条路线补充实用交通描述和注意事项
    - 让用户偏好在最关键的位置上体现出来，而不是只出现在泛泛描述中
    - 每个景点都给出合理的停留时长、参观优先级和与偏好的关联原因
    - 每天标题应采用简洁说明式，例如“第1天｜城堡山步行串联（老城地标+河景）”，不要使用夸张词
    - 每家餐馆必须提供有效 address、latitude、longitude，并优先选择距离当天对应景点锚点更近的候选
    - 防止偏好极端化：同类景点与同菜系餐饮不可占满整日安排；需体现“主偏好 + 辅助体验”的结构
    - 所有 activities 都要输出 `preference_matched` 和 `preference_reason`（不匹配可给空字符串）
    - 只允许基于输入的候选池中的景点与餐饮生成计划，禁止自行编造不存在的景点、餐厅、地址、经纬度或主题。
    - 如果候选池为空或不足，必须优先缩小当天安排范围，使用已有候选进行组合，不要臆造新地点。
    - 严禁在输出中写出你的思考过程、解释、反思、调试信息或对规则的自我讨论；只输出合法 JSON。

    请直接输出 JSON，不要添加任何解释文字。输出结构参考以下示例：
    {schema_text}
    """
).strip()

REFLECTION_PROMPT_TEMPLATE = dedent(
    """
    你现在是严格的旅行计划审核专家。
    请对下面这份初始旅行计划进行批判性反思和优化：

    初始计划：
    {initial_plan_json}

    原始景点数据：
    {attractions_json}

    反思 checklist：
    - 路线是否符合真实地理和交通逻辑？是否存在不合理跳跃？
    - 时间安排是否太赶？是否有足够休息和用餐时间？
    - 预算是否现实（中档标准）？
    - 是否充分利用了提供的景点数据？
    - 是否有明显的不合理之处？
    - 每天标题是否克制、可解释（明确区域/主题/节奏），避免“梦幻、史诗、炸裂、必打卡神线”等夸张表达？
    - 偏好是否被过度放大为单一内容灌满（如全程同类景点/同菜系餐饮）？若是，请在保持偏好优先的前提下增加互补体验。

    请直接输出优化后的完整 JSON（保持相同结构），不要添加任何解释。
    """
).strip()


def _build_search_strategy_prompt(location: str, days: int, preferences: str) -> str:
    return SEARCH_STRATEGY_PROMPT.format(
        location=location,
        days=days,
        preferences=preferences,
    )


def _build_user_prompt(location: str, days: int, preferences: str, search_strategy: str, attractions_json: str, meals_json: str, daily_buckets_json: str) -> str:
    schema_text = json.dumps(TRAVEL_PLAN_SCHEMA_EXAMPLE, ensure_ascii=False, indent=2)
    return TRAVEL_PLAN_PROMPT_TEMPLATE.format(
        location=location,
        days=days,
        preferences=preferences,
        search_strategy=search_strategy,
        attractions_json=attractions_json,
        meals_json=meals_json,
        daily_buckets_json=daily_buckets_json,
        schema_text=schema_text,
    )


def _build_reflection_prompt(initial_plan_json: str, attractions_json: str) -> str:
    return REFLECTION_PROMPT_TEMPLATE.format(
        initial_plan_json=initial_plan_json,
        attractions_json=attractions_json,
    )


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


def _truncate_text(text: str, limit: int = 1200) -> str:
    if len(text) <= limit:
        return text
    return f"{text[:limit]} ...(truncated, total_chars={len(text)})"


def _preview_text(text: str, *, max_chars: int | None = None) -> str:
    if max_chars is None:
        return text or ""
    return _truncate_text(text or "", max_chars)


def _log_step(message: str) -> None:
    ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    print(f"{ts} [travel-plan][step] {message}")


def _log_stage(stage: str, message: str) -> None:
    ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    print(f"{ts} [travel-plan][stage:{stage}] {message}")


def _log_llm_debug(stage: str, payload: Dict[str, Any]) -> None:
    ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    print(f"{ts} [travel-plan][llm-debug][{stage}] {json.dumps(payload, ensure_ascii=False)}")


def _sse_event(event: str, data: Dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _summarize_itinerary(plan: Dict[str, Any]) -> List[str]:
    itinerary = plan.get("itinerary")
    if not isinstance(itinerary, list):
        return []
    summaries: List[str] = []
    for day in itinerary:
        if not isinstance(day, dict):
            continue
        day_no = day.get("day", "?")
        title = day.get("title", "")
        activities = day.get("activities")
        act_count = len(activities) if isinstance(activities, list) else 0
        summaries.append(f"day={day_no}, title={title}, activities={act_count}")
    return summaries


def _build_llm_debug_payload(stage: str, *, prompt: str, raw_content: str, parsed_obj: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "stage": stage,
        "prompt_chars": len(prompt),
        "prompt_preview": _preview_text(prompt, max_chars=4000),
        "raw_content_chars": len(raw_content or ""),
        "raw_content_preview": _preview_text(raw_content, max_chars=4000),
        "parsed_summary": _summarize_itinerary(parsed_obj),
        "parsed_keys": list(parsed_obj.keys()) if isinstance(parsed_obj, dict) else [],
    }


def _print_llm_debug(stage: str, *, prompt: str, raw_content: str, parsed_obj: Dict[str, Any]) -> None:
    payload = _build_llm_debug_payload(stage, prompt=prompt, raw_content=raw_content, parsed_obj=parsed_obj)
    _log_llm_debug(f"{stage}:prompt", {"chars": payload["prompt_chars"], "preview": payload["prompt_preview"]})
    _log_llm_debug(f"{stage}:raw", {"chars": payload["raw_content_chars"], "preview": payload["raw_content_preview"]})
    _log_llm_debug(f"{stage}:parsed", {"summary": payload["parsed_summary"], "keys": payload["parsed_keys"]})


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
                "editorial_summary": item.get("editorial_summary"),
                "suggested_stay_minutes": item.get("suggested_stay_minutes"),
                "visit_style": item.get("visit_style", "standard"),
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
    title = f"第{day_index + 1}天 · {theme or '主题游览'}"
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
                "route_desc": "优先根据现场情况选择符合主题的地点，不做虚构景点。",
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
        theme = str(bucket.get("theme") or f"第{idx + 1}天")
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
        "tips": ["候选池较少，已使用可用景点与餐饮生成保守行程。"],
        "warnings": warnings or ["景点候选池不足，部分日期已降级为保守安排。"],
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
            return f"第{day_no}天｜{summary_brief}"
        return f"第{day_no}天｜区域步行与主题游览"

    if not cleaned.startswith(f"第{day_no}天"):
        cleaned = f"第{day_no}天｜{cleaned}"
    return cleaned


def _is_citywalk_preference(preferences: str) -> bool:
    text = (preferences or "").lower()
    citywalk_keywords = ["citywalk", "城市漫步", "city walk", "walk", "步行", "走马观花", "逛街", "街区"]
    return any(k in text for k in citywalk_keywords)


def _ensure_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


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


def _build_theme_fallbacks(location: str, day: int, theme: str, theme_tags: List[str], preferences: str) -> tuple[List[str], List[str]]:
    tags = [str(t).strip() for t in theme_tags if str(t).strip()]
    pref_tags = [p.strip() for p in preferences.replace("；", ",").replace("/", ",").split(",") if p.strip()]
    seeds = tags[:3] or pref_tags[:2] or [theme or "经典景点"]
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
        f"{location} 经典景点",
        f"{location} 城市地标",
    ])
    meal_queries = [f"{location} {seed} 餐厅" for seed in seeds[:2]]
    meal_queries.extend([f"{location} 当地美食", f"{location} 特色餐厅", f"{location} 市中心餐厅"])
    return attraction_queries[:6], meal_queries[:4]


@router.post(
    "/stream",
    summary="Google Places 旅行规划流式输出",
    description="以 SSE 方式实时返回进度、阶段描述和最终结果。",
)
async def generate_travel_plan_stream(req: TravelPlanRequest):
    async def event_generator():
        started = time.perf_counter()
        settings = get_settings()
        llm_debug_enabled = bool(settings.debug)
        try:
            yield _sse_event("progress", {"percent": 1, "status": "初始化规划任务..."})
            yield _sse_event("log", {"message": f"开始规划: {req.location} / {req.days}天 / {req.preferences or '-'}"})
            _log_stage("start", f"location={req.location}, days={req.days}, preferences={req.preferences or '-'}")

            service = get_google_places_service()
            router = get_llm_router()
            yield _sse_event("progress", {"percent": 8, "status": "正在生成搜索策略..."})
            strategy_prompt = _build_search_strategy_prompt(req.location, req.days, req.preferences or "no special preference")
            _log_stage("strategy", f"prompt_ready chars={len(strategy_prompt)}")
            strategy_start = time.perf_counter()
            strategy_result = await router.generate_json(location=req.location, days=req.days, preferences=req.preferences or "", system_prompt=SYSTEM_PROMPT, user_prompt=strategy_prompt, temperature=0.2, step="strategy")
            strategy_elapsed = int((time.perf_counter() - strategy_start) * 1000)
            _log_stage("strategy", f"llm_done model={strategy_result.model}, elapsed_ms={strategy_elapsed}, input_tokens={strategy_result.input_tokens}, output_tokens={strategy_result.output_tokens}, cost_usd={strategy_result.cost_usd:.6f}")
            strategy_obj = _extract_json_object(strategy_result.content)
            _log_stage("strategy", f"json_parsed valid={bool(strategy_obj)}, keys={list(strategy_obj.keys()) if isinstance(strategy_obj, dict) else []}")
            yield _sse_event("step", {"name": "strategy", "status": "done", "description": "已生成搜索策略"})
            strategy_debug = _build_llm_debug_payload("strategy", prompt=strategy_prompt, raw_content=strategy_result.content, parsed_obj=strategy_obj)
            _log_llm_debug("strategy", strategy_debug)
            yield _sse_event("llm_debug", strategy_debug)
            if llm_debug_enabled:
                _print_llm_debug("strategy", prompt=strategy_prompt, raw_content=strategy_result.content, parsed_obj=strategy_obj)

            strategy_daily_themes = _ensure_list(strategy_obj.get("daily_themes") if isinstance(strategy_obj, dict) else [])
            if len(strategy_daily_themes) != req.days:
                _log_stage("strategy", f"daily_themes_invalid count={len(strategy_daily_themes)}, fallback_to_flat_queries")
                strategy_daily_themes = []
            citywalk_mode = _is_citywalk_preference(req.preferences or "")
            base_candidate_limit = _calc_candidate_limit(req.days)
            raw_limit = min(20, max(8, (base_candidate_limit // 2) if citywalk_mode else base_candidate_limit))
            _log_stage("limit", f"citywalk_mode={citywalk_mode}, base_candidate_limit={base_candidate_limit}, raw_limit={raw_limit}")

            raw_attractions: List[Dict[str, Any]] = []
            attractions: List[Dict[str, Any]] = []
            meal_candidates: List[Dict[str, Any]] = []
            daily_buckets: List[Dict[str, Any]] = []
            daily_meal_sources: Dict[int, Dict[str, Any]] = {}
            generation_warnings: List[str] = []
            meal_stats = {"total": 0, "geo_valid": 0, "address_valid": 0}

            if strategy_daily_themes:
                yield _sse_event("progress", {"percent": 18, "status": "正在按天主题检索候选..."})
                for theme_day in strategy_daily_themes:
                    if not isinstance(theme_day, dict):
                        continue
                    day_index = int(theme_day.get("day") or 0)
                    theme = str(theme_day.get("theme") or f"第{day_index}天")
                    theme_tags = _ensure_list(theme_day.get("theme_tags"))
                    attraction_queries = _ensure_list(theme_day.get("attraction_queries"))
                    meal_queries = _ensure_list(theme_day.get("meal_queries"))
                    if not attraction_queries or not meal_queries:
                        attraction_queries, meal_queries = _build_theme_fallbacks(req.location, day_index, theme, theme_tags, req.preferences or "")
                    _log_stage("daily_theme", f"day={day_index}, theme={theme}, tags={theme_tags}, attraction_queries={len(attraction_queries[:4])}, meal_queries={len(meal_queries[:3])}")

                    day_attraction_raw: List[Dict[str, Any]] = []
                    for q_idx, query in enumerate(attraction_queries[:4], start=1):
                        try:
                            _log_stage("daily_theme.attraction", f"day={day_index}, query[{q_idx}] start={query}")
                            query_start = time.perf_counter()
                            per_query_limit = max(5, min((raw_limit // 2) if citywalk_mode else (raw_limit // 3), 10))
                            items = service.search_places(str(query), limit=per_query_limit)
                            day_attraction_raw.extend(items)
                            raw_attractions.extend(items)
                            query_elapsed = int((time.perf_counter() - query_start) * 1000)
                            _log_stage("daily_theme.attraction", f"day={day_index}, query[{q_idx}] done count={len(items)} elapsed_ms={query_elapsed}")
                        except Exception as attraction_exc:
                            _log_stage("daily_theme.attraction", f"day={day_index}, query[{q_idx}] failed error={attraction_exc}")

                    day_attractions = _normalize_attractions(day_attraction_raw)[:8]
                    day_meals, day_meal_source, day_meal_stats = _collect_meals_near_anchors(
                        service,
                        location=req.location,
                        day_index=day_index,
                        meal_queries=meal_queries,
                        day_attractions=day_attractions,
                    )
                    meal_stats["total"] += day_meal_stats["total"]
                    meal_stats["geo_valid"] += day_meal_stats["geo_valid"]
                    meal_stats["address_valid"] += day_meal_stats["address_valid"]
                    daily_meal_sources[day_index] = day_meal_source
                    _log_stage(
                        "daily_theme.meal",
                        f"day={day_index}, candidates_total={day_meal_stats['total']}, "
                        f"geo_valid={day_meal_stats['geo_valid']}, address_valid={day_meal_stats['address_valid']}, "
                        f"selected={len(day_meals)}",
                    )
                    daily_buckets.append({
                        "day": day_index,
                        "theme": theme,
                        "theme_tags": theme_tags,
                        "attractions": day_attractions,
                        "meals": _compact_meals_for_llm(day_meals, max_items=6),
                    })
                    attractions.extend(day_attractions)
                    meal_candidates.extend(day_meals)
                    _log_stage("daily_theme", f"day={day_index} bucket_ready attractions={len(daily_buckets[-1]['attractions'])}, meals={len(daily_buckets[-1]['meals'])}")
            else:
                attraction_queries = _ensure_list(strategy_obj.get("attraction_queries") if isinstance(strategy_obj, dict) else [])
                meal_queries = _ensure_list(strategy_obj.get("meal_queries") if isinstance(strategy_obj, dict) else [])
                if not attraction_queries:
                    attraction_queries = [f"{req.location} 代表性景点 attractions", f"{req.location} 博物馆 历史景点"]
                if not meal_queries:
                    meal_queries = [f"{req.location} 早餐", f"{req.location} 午餐 餐厅", f"{req.location} 晚餐 餐厅"]

                yield _sse_event("progress", {"percent": 18, "status": "正在检索景点候选..."})
                _log_stage("attraction_search", f"start limit={raw_limit}, query_count={len(attraction_queries[:3])}")
                for idx, query in enumerate(attraction_queries[:3], start=1):
                    try:
                        _log_stage("attraction_search", f"query[{idx}] start={query}")
                        query_start = time.perf_counter()
                        items = service.search_places(str(query), limit=raw_limit)
                        raw_attractions.extend(items)
                        query_elapsed = int((time.perf_counter() - query_start) * 1000)
                        _log_stage("attraction_search", f"query[{idx}] done count={len(items)} elapsed_ms={query_elapsed}")
                        yield _sse_event("log", {"message": f"景点检索完成[{idx}]: {query} / {len(items)}条"})
                        yield _sse_event("step", {"name": f"attraction_query_{idx}", "status": "done", "description": f"景点候选检索完成 {len(items)} 条"})
                    except Exception as attraction_exc:
                        _log_stage("attraction_search", f"query[{idx}] failed error={attraction_exc}")
                        yield _sse_event("log", {"message": f"景点检索失败[{idx}]: {query} / {attraction_exc}"})
                        yield _sse_event("step", {"name": f"attraction_query_{idx}", "status": "error", "description": f"景点候选检索失败: {attraction_exc}"})
                attractions = _normalize_attractions(raw_attractions)
                _log_stage("attraction_search", f"merged raw={len(raw_attractions)}, normalized={len(attractions)}")

                yield _sse_event("progress", {"percent": 32, "status": "正在检索餐饮候选..."})
                meal_limit = min(max(req.days * 3, 6), 12)
                _log_stage("meal_search", f"start limit={meal_limit}, query_count={len(meal_queries[:3])}")
                day_attractions = attractions[:8]
                fallback_day_index = 1
                day_meals, day_meal_source, day_meal_stats = _collect_meals_near_anchors(
                    service,
                    location=req.location,
                    day_index=fallback_day_index,
                    meal_queries=meal_queries,
                    day_attractions=day_attractions,
                )
                meal_stats["total"] += day_meal_stats["total"]
                meal_stats["geo_valid"] += day_meal_stats["geo_valid"]
                meal_stats["address_valid"] += day_meal_stats["address_valid"]
                daily_meal_sources[fallback_day_index] = day_meal_source
                meal_candidates.extend(day_meals)
                meal_candidates = meal_candidates[:meal_limit]
                _log_stage("meal_search", f"merged candidates={len(meal_candidates)}")

                day_meals = _compact_meals_for_llm(meal_candidates)
                daily_buckets.append({
                    "day": 1,
                    "theme": "fallback",
                    "theme_tags": [],
                    "attractions": day_attractions,
                    "meals": day_meals,
                })

            _log_stage(
                "meal_quality",
                f"meal_candidates_total={meal_stats['total']}, "
                f"meal_candidates_geo_valid={meal_stats['geo_valid']}, meal_candidates_address_valid={meal_stats['address_valid']}",
            )

            daily_buckets_json = json.dumps(daily_buckets, ensure_ascii=False)
            _log_stage("daily_theme", f"buckets_built count={len(daily_buckets)} chars={len(daily_buckets_json)}")

            yield _sse_event("progress", {"percent": 48, "status": "正在生成行程初稿..."})
            compact_attractions_json = json.dumps(_compact_attractions_for_llm(attractions[: _calc_candidate_limit(req.days)]), ensure_ascii=False)
            compact_meals_json = json.dumps(_compact_meals_for_llm(meal_candidates), ensure_ascii=False)
            _log_stage("generation", f"payload_ready attractions_chars={len(compact_attractions_json)}, meals_chars={len(compact_meals_json)}, daily_buckets_chars={len(daily_buckets_json)}")
            user_prompt = _build_user_prompt(req.location, req.days, req.preferences or "no special preference", json.dumps({**strategy_obj, "daily_buckets": daily_buckets}, ensure_ascii=False), compact_attractions_json, compact_meals_json, daily_buckets_json)
            _log_stage("generation", f"prompt_built chars={len(user_prompt)}")
            if llm_debug_enabled:
                _print_llm_debug("generation_prompt", prompt=user_prompt, raw_content="", parsed_obj={})
                yield _sse_event("llm_debug", {"stage": "generation_prompt", "prompt": _preview_text(user_prompt, max_chars=1800), "attractions_count": len(attractions), "meal_candidates_count": len(meal_candidates)})
            if not daily_buckets:
                _log_stage("generation", "daily_buckets_empty_using_compact_candidates_only")
            generation_start = time.perf_counter()
            generation_result = await router.generate_json(location=req.location, days=req.days, preferences=req.preferences or "", system_prompt=SYSTEM_PROMPT, user_prompt=user_prompt, temperature=0.2, step="generation")
            generation_elapsed = int((time.perf_counter() - generation_start) * 1000)
            _log_stage("generation", f"llm_done model={generation_result.model}, elapsed_ms={generation_elapsed}, input_tokens={generation_result.input_tokens}, output_tokens={generation_result.output_tokens}, cost_usd={generation_result.cost_usd:.6f}")
            generation_obj = _extract_json_object(generation_result.content)
            _log_stage("generation", f"json_parsed valid={bool(generation_obj)}, keys={list(generation_obj.keys()) if isinstance(generation_obj, dict) else []}")
            if not generation_obj:
                _log_stage("generation", "json_invalid_retry_with_stricter_prompt")
                retry_prompt = user_prompt + "\n\n强制要求：只能输出合法 JSON，不允许任何思考、解释、markdown、代码块、附加文本；如果候选不足，只能缩短行程或返回空数组，不得编造。"
                retry_start = time.perf_counter()
                retry_result = await router.generate_json(location=req.location, days=req.days, preferences=req.preferences or "", system_prompt=SYSTEM_PROMPT, user_prompt=retry_prompt, temperature=0.0, step="generation_retry")
                retry_elapsed = int((time.perf_counter() - retry_start) * 1000)
                _log_stage("generation_retry", f"llm_done model={retry_result.model}, elapsed_ms={retry_elapsed}, input_tokens={retry_result.input_tokens}, output_tokens={retry_result.output_tokens}, cost_usd={retry_result.cost_usd:.6f}")
                generation_obj = _extract_json_object(retry_result.content)
                _log_stage("generation_retry", f"json_parsed valid={bool(generation_obj)}, keys={list(generation_obj.keys()) if isinstance(generation_obj, dict) else []}")
                if llm_debug_enabled:
                    _print_llm_debug("generation_retry", prompt=retry_prompt, raw_content=retry_result.content, parsed_obj=generation_obj)
            if not generation_obj:
                generation_warnings = ["LLM 输出无效，已使用候选池生成保守兜底行程。"]
                generation_obj = _build_fallback_plan(req.location, req.days, daily_buckets, attractions, meal_candidates, generation_warnings)
                _log_stage("generation", f"fallback_plan_built days={len(generation_obj.get('itinerary', []))}")
            yield _sse_event("step", {"name": "generation", "status": "done", "description": "已生成初稿"})
            if llm_debug_enabled:
                _print_llm_debug("generation", prompt=user_prompt, raw_content=generation_result.content, parsed_obj=generation_obj)
                yield _sse_event("llm_debug", {"stage": "generation", "raw": generation_result.content, "summary": _summarize_itinerary(generation_obj), "prompt": _preview_text(user_prompt, max_chars=1800)})

            final_obj = generation_obj
            reflection_source_attractions = daily_buckets_json if daily_buckets_json else json.dumps(attractions, ensure_ascii=False)
            yield _sse_event("progress", {"percent": 74, "status": "正在进行反思优化..."})
            reflection_prompt = _build_reflection_prompt(json.dumps(generation_obj, ensure_ascii=False), reflection_source_attractions)
            _log_stage("reflection", f"prompt_built chars={len(reflection_prompt)}")
            reflection_start = time.perf_counter()
            reflection_result = await router.generate_json(location=req.location, days=req.days, preferences=req.preferences or "", system_prompt=SYSTEM_PROMPT, user_prompt=reflection_prompt, temperature=0.3, step="reflection")
            reflection_elapsed = int((time.perf_counter() - reflection_start) * 1000)
            _log_stage("reflection", f"llm_done model={reflection_result.model}, elapsed_ms={reflection_elapsed}, input_tokens={reflection_result.input_tokens}, output_tokens={reflection_result.output_tokens}, cost_usd={reflection_result.cost_usd:.6f}")
            reflection_obj = _extract_json_object(reflection_result.content)
            _log_stage("reflection", f"json_parsed valid={bool(reflection_obj)}, keys={list(reflection_obj.keys()) if isinstance(reflection_obj, dict) else []}")
            if reflection_obj:
                final_obj = reflection_obj
                yield _sse_event("step", {"name": "reflection", "status": "done", "description": "已完成反思优化"})
                if llm_debug_enabled:
                    _print_llm_debug("reflection", prompt=reflection_prompt, raw_content=reflection_result.content, parsed_obj=reflection_obj)
                    yield _sse_event("llm_debug", {"stage": "reflection", "raw": reflection_result.content, "summary": _summarize_itinerary(reflection_obj), "prompt": _preview_text(reflection_prompt, max_chars=1800)})
            else:
                _log_stage("reflection", "invalid fallback to generation result")
                yield _sse_event("log", {"message": "反思结果无效，已回退到初稿"})

            final_obj.setdefault("warnings", [])
            if isinstance(final_obj.get("warnings"), list) and generation_warnings:
                final_obj["warnings"] = list(dict.fromkeys([*final_obj.get("warnings", []), *generation_warnings]))
            itinerary_raw = _ensure_list(final_obj.get("itinerary"))
            itinerary_raw, meal_validation_metrics = _enforce_meal_quality_on_itinerary(
                service=service,
                location=req.location,
                itinerary=itinerary_raw,
                daily_meal_sources=daily_meal_sources,
            )
            _log_stage(
                "meal_quality",
                f"meal_selected_within_radius={meal_validation_metrics['meal_selected_within_radius']}, "
                f"meal_missing_geo={meal_validation_metrics['meal_missing_geo']}, "
                f"meal_missing_address={meal_validation_metrics['meal_missing_address']}",
            )
            normalized_itinerary: List[Dict[str, Any]] = []
            meal_place_map_by_id = {str(m.get("place_id") or ""): m for m in meal_candidates if str(m.get("place_id") or "").strip()}
            meal_place_map_by_name = {str(m.get("name") or ""): m for m in meal_candidates}
            _log_stage("normalize", f"start itinerary_days={len(itinerary_raw)}, meal_place_map_id={len(meal_place_map_by_id)}, meal_place_map_name={len(meal_place_map_by_name)}")
            for day in itinerary_raw:
                if not isinstance(day, dict):
                    continue
                activities = []
                for act in day.get("activities") or []:
                    if not isinstance(act, dict):
                        continue
                    ticket_price = act.get("ticket_price")
                    if ticket_price in (None, ""):
                        ticket_price = 0
                        act_name = str(act.get("name") or "")
                        for attraction in attractions:
                            if str(attraction.get("name") or "") == act_name:
                                ticket_price = attraction.get("ticket_price", 0) or 0
                                break
                    activities.append({**act, "ticket_price": ticket_price})
                activities[-1]["preference_matched"] = bool(act.get("preference_matched"))
                activities[-1]["preference_reason"] = str(act.get("preference_reason") or "")
                meals: List[Dict[str, Any]] = []
                for meal in day.get("meals") or []:
                    if not isinstance(meal, dict):
                        continue
                    meal_place_id = str(meal.get("place_id") or "")
                    meal_name = str(meal.get("name") or "")
                    source_meal = meal_place_map_by_id.get(meal_place_id) if meal_place_id else None
                    if not source_meal:
                        source_meal = meal_place_map_by_name.get(meal_name)
                    if source_meal:
                        meal = {
                            **meal,
                            "address": meal.get("address") or source_meal.get("address") or source_meal.get("formatted_address") or "",
                            "latitude": meal.get("latitude") if meal.get("latitude") is not None else source_meal.get("latitude"),
                            "longitude": meal.get("longitude") if meal.get("longitude") is not None else source_meal.get("longitude"),
                            "estimated_cost": meal.get("estimated_cost") or source_meal.get("estimated_cost") or 0,
                            "place_id": meal.get("place_id") or source_meal.get("place_id") or "",
                        }
                    meals.append({**meal})
                day_no = int(day.get("day") or (len(normalized_itinerary) + 1))
                normalized_title = _normalize_day_title(day_no, str(day.get("title") or ""), str(day.get("route_summary") or ""))
                normalized_itinerary.append({**day, "title": normalized_title, "activities": activities, "meals": meals})

            data = TravelPlanData(
                location=str(final_obj.get("location") or req.location),
                days=int(final_obj.get("days") or req.days),
                attractions=_dedupe_by_name(attractions),
                itinerary=normalized_itinerary,
                total_budget=final_obj.get("total_budget") or {"transport": 0, "tickets": 0, "food": 0, "total": 0, "currency": "EUR"},
                tips=[str(x) for x in (final_obj.get("tips") or []) if str(x).strip()],
                warnings=[str(x) for x in (final_obj.get("warnings") or []) if str(x).strip()],
            )
            store = get_travel_plan_store()
            saved_payload = data.model_dump()
            result_id = store.save(saved_payload)
            _log_stage("normalize", f"done days={len(normalized_itinerary)}, tips={len(data.tips)}, warnings={len(data.warnings)}")
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            _log_stage("done", f"elapsed_ms={elapsed_ms}, generation_cost_usd={generation_result.cost_usd:.6f}, reflection_cost_usd={(reflection_result.cost_usd if 'reflection_result' in locals() else 0.0):.6f}")
            yield _sse_event("progress", {"percent": 100, "status": "生成完成"})
            yield _sse_event("done", {"success": True, "message": "生成成功", "data": {**saved_payload, "result_id": result_id}, "result_id": result_id, "elapsed_ms": elapsed_ms})
        except Exception as e:
            _log_stage("error", f"type={type(e).__name__}, error={e}")
            yield _sse_event("error", {"message": str(e), "detail": repr(e)})

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.get(
    "/results",
    summary="获取旅行规划记录列表",
)
async def list_travel_plan_results(limit: int = 100):
    store = get_travel_plan_store()
    items = store.list(limit=limit)
    return {"success": True, "items": items}


@router.get(
    "/results/{result_id}",
    summary="获取单个旅行规划记录",
)
async def get_travel_plan_result(result_id: str):
    store = get_travel_plan_store()
    record = store.get(result_id)
    if not record:
        raise HTTPException(status_code=404, detail="记录不存在")
    payload = record.get("payload") or {}
    return {
        "success": True,
        "id": result_id,
        "created_at": record.get("created_at"),
        "updated_at": record.get("updated_at"),
        "data": {**payload, "result_id": result_id},
    }


@router.delete(
    "/results/{result_id}",
    summary="删除单个旅行规划记录",
)
async def delete_travel_plan_result(result_id: str):
    store = get_travel_plan_store()
    ok = store.delete(result_id)
    if not ok:
        raise HTTPException(status_code=404, detail="记录不存在")
    return {"success": True, "id": result_id}
