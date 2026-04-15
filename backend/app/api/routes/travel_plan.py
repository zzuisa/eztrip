"""Google Places 旅行规划 API（LLM 直出 JSON）"""

from __future__ import annotations

import json
import time
from textwrap import dedent
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from ...config import get_settings
from ...models.schemas import TravelPlanRequest, TravelPlanResponseV2, TravelPlanData
from ...services.google_places_service import get_google_places_service
from ...services.llm_service import get_llm_router

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
                }
            ],
        }
    ],
    "tips": ["string"],
    "warnings": ["string"],
}

SEARCH_STRATEGY_PROMPT = dedent(
    """
    你是旅行规划搜索策略专家。
    根据用户输入，先输出一份用于检索 Google Places 的结构化搜索策略。

    用户输入地点：{location}
    天数：{days} 天
    用户偏好：{preferences}

    请只输出 JSON，结构如下：
    {{
      "attraction_queries": ["query1", "query2"],
      "meal_queries": ["query1", "query2", "query3"],
      "focus_tags": ["museum", "food", "nature"],
      "pace": "relaxed|standard|deep",
      "budget_level": "low|mid|high",
      "must_include": ["museum", "historic center"],
      "avoid": ["shopping", "theme park"]
    }}

    要求：
    - attraction_queries 至少 2 条，优先覆盖用户偏好与地点核心主题。
    - meal_queries 至少 3 条，分别偏向早餐、午餐、晚餐。
    - focus_tags 和 must_include 要尽量直接体现用户偏好关键词。
    - avoid 仅在用户明显表达排斥时填写，否则留空数组。
    """
).strip()

TRAVEL_PLAN_PROMPT_TEMPLATE = dedent(
    """
    任务背景
    - 用户输入地点：{location}
    - 天数：{days} 天
    - 用户偏好（必须优先满足，作为关键规划约束）：{preferences}
    - 检索策略重点：{search_strategy}

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

    以下是 Google Places API 返回的真实景点数据（请严格使用这些数据）：
    {attractions_json}

    以下是餐饮候选数据（同样来自 Google Places，请就近搭配）：
    {meals_json}

    请充分发挥你的规划能力，完成以下任务：
    - 对景点进行合理的空间分组和路线规划（考虑真实交通逻辑）
    - 生成一份连贯、可执行的 {days} 天旅行计划
    - 每天安排 3–5 个景点，并包含早餐、午餐、晚餐
    - 餐饮也请使用 Google Places 风格的位置数据输出，且尽量在景点附近或路线上
    - 展示每个景点的门票价格；如无门票则明确写 0
    - 计算现实的每日和总预算（中档标准）
    - 为每条路线补充实用交通描述和注意事项
    - 让用户偏好在最关键的位置上体现出来，而不是只出现在泛泛描述中
    - 每个景点都给出合理的停留时长、参观优先级和与偏好的关联原因

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

    请直接输出优化后的完整 JSON（保持相同结构），不要添加任何解释。
    """
).strip()


def _build_search_strategy_prompt(location: str, days: int, preferences: str) -> str:
    return SEARCH_STRATEGY_PROMPT.format(
        location=location,
        days=days,
        preferences=preferences,
    )


def _build_user_prompt(location: str, days: int, preferences: str, search_strategy: str, attractions_json: str, meals_json: str) -> str:
    schema_text = json.dumps(TRAVEL_PLAN_SCHEMA_EXAMPLE, ensure_ascii=False, indent=2)
    return TRAVEL_PLAN_PROMPT_TEMPLATE.format(
        location=location,
        days=days,
        preferences=preferences,
        search_strategy=search_strategy,
        attractions_json=attractions_json,
        meals_json=meals_json,
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


def _print_llm_debug(stage: str, *, prompt: str, raw_content: str, parsed_obj: Dict[str, Any]) -> None:
    print(f"[travel-plan][llm-debug][{stage}] prompt_chars={len(prompt)}")
    print(f"[travel-plan][llm-debug][{stage}] prompt_preview={_preview_text(prompt, max_chars=1200)}")
    print(f"[travel-plan][llm-debug][{stage}] raw_content_chars={len(raw_content or '')}")
    print(f"[travel-plan][llm-debug][{stage}] raw_content_preview={_preview_text(raw_content)}")
    print(
        f"[travel-plan][llm-debug][{stage}] parsed_summary="
        f"{json.dumps(_summarize_itinerary(parsed_obj), ensure_ascii=False)}"
    )


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


def _calc_candidate_limit(days: int) -> int:
    return min(max(days * 4, 10), 18)


@router.post(
    "",
    response_model=TravelPlanResponseV2,
    summary="Google Places 模糊地点旅行规划（LLM 直出 JSON）",
    description="调用 Google Places 获取景点后，将原始候选交给 LLM 生成完整可执行行程，不在服务端写规划规则。",
    responses={
        200: {
            "description": "生成成功",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "生成成功",
                        "data": {
                            "location": "法国 巴黎",
                            "days": 5,
                            "attractions": [
                                {
                                    "name": "埃菲尔铁塔",
                                    "lat": 48.8584,
                                    "lng": 2.2945,
                                    "route_desc": "地铁+步行约25分钟",
                                    "formatted_address": "Champ de Mars, Paris, France",
                                    "rating": 4.7,
                                    "editorial_summary": "巴黎地标",
                                    "place_id": "ChIJ...",
                                }
                            ],
                            "itinerary": [
                                {
                                    "day": 1,
                                    "title": "巴黎西区经典一日",
                                    "route_length": "由 LLM 生成",
                                    "activities": ["..."],
                                }
                            ],
                            "total_budget": {"transport": 120, "tickets": 260, "total": 380},
                            "tips": ["..."],
                        },
                    }
                }
            },
        }
    },
)
async def generate_travel_plan(req: TravelPlanRequest):
    started = time.perf_counter()
    settings = get_settings()
    llm_debug_enabled = bool(settings.debug)
    try:
        print(f"🚀 [travel-plan][start] location={req.location}, days={req.days}, preferences={req.preferences or '-'}")
        print("🗺️ [travel-plan][step] starting to call Google Places API")

        t0 = time.perf_counter()
        service = get_google_places_service()
        search_strategy_prompt = _build_search_strategy_prompt(req.location, req.days, req.preferences or "no special preference")
        print("🧠 [travel-plan][step] search strategy generation start")
        strategy_start = time.perf_counter()
        strategy_result = await get_llm_router().generate_json(
            location=req.location,
            days=req.days,
            preferences=req.preferences or "",
            system_prompt=SYSTEM_PROMPT,
            user_prompt=search_strategy_prompt,
            temperature=0.2,
            step="strategy",
        )
        strategy_elapsed = int((time.perf_counter() - strategy_start) * 1000)
        print(f"🎯 [travel-plan][step] search strategy finished: model={strategy_result.model}, elapsed_ms={strategy_elapsed}, input_tokens={strategy_result.input_tokens}, output_tokens={strategy_result.output_tokens}, cost_usd={strategy_result.cost_usd:.6f}")
        strategy_obj = _extract_json_object(strategy_result.content)
        if llm_debug_enabled:
            _print_llm_debug(
                "strategy",
                prompt=search_strategy_prompt,
                raw_content=strategy_result.content,
                parsed_obj=strategy_obj,
            )
        attraction_queries = strategy_obj.get("attraction_queries") if isinstance(strategy_obj, dict) else None
        meal_queries = strategy_obj.get("meal_queries") if isinstance(strategy_obj, dict) else None
        if not isinstance(attraction_queries, list) or not attraction_queries:
            attraction_queries = [f"{req.location} 代表性景点 attractions", f"{req.location} 博物馆 历史景点"]
        if not isinstance(meal_queries, list) or not meal_queries:
            meal_queries = [f"{req.location} 早餐", f"{req.location} 午餐 餐厅", f"{req.location} 晚餐 餐厅"]

        raw_limit = _calc_candidate_limit(req.days)
        raw_attractions: List[Dict[str, Any]] = []
        for query in attraction_queries[:3]:
            try:
                raw_attractions.extend(service.search_places(str(query), limit=raw_limit))
            except Exception as attraction_exc:
                print(f"[travel-plan][warn] attraction_query_failed={query}, error={attraction_exc}")
        attractions = _normalize_attractions(raw_attractions)
        prompt_limit = _calc_candidate_limit(req.days)
        prompt_attractions = attractions[: min(len(attractions), prompt_limit)]
        meal_candidates: List[Dict[str, Any]] = []
        meal_limit = min(max(req.days * 3, 6), 12)
        for meal_query in meal_queries[:3]:
            try:
                meal_candidates.extend(service.search_places(str(meal_query), limit=max(2, meal_limit // 3)))
            except Exception as meal_exc:
                print(f"[travel-plan][warn] meal_query_failed={meal_query}, error={meal_exc}")
        meal_candidates = meal_candidates[:meal_limit]
        t1 = time.perf_counter()
        print(f"✅ [travel-plan][step] Google Places API finished: raw={len(raw_attractions)}, normalized={len(attractions)}, prompt_used={len(prompt_attractions)}, meal_candidates={len(meal_candidates)}, elapsed_ms={int((t1 - t0) * 1000)}")

        print("🧩 [travel-plan][step] building LLM prompt")
        prompt_build_start = time.perf_counter()
        compact_attractions_json = json.dumps(_compact_attractions_for_llm(prompt_attractions), ensure_ascii=False)
        compact_meals_json = json.dumps(_compact_meals_for_llm(meal_candidates), ensure_ascii=False)
        user_prompt = _build_user_prompt(
            req.location,
            req.days,
            req.preferences or "no special preference",
            json.dumps(strategy_obj, ensure_ascii=False),
            compact_attractions_json,
            compact_meals_json,
        )
        prompt_build_elapsed = int((time.perf_counter() - prompt_build_start) * 1000)
        print(f"📝 [travel-plan][step] prompt ready: built_elapsed_ms={prompt_build_elapsed}, prompt_chars={len(user_prompt)}")

        print("🧠 [travel-plan][step] LLM generation start")
        llm_start = time.perf_counter()
        router = get_llm_router()
        generation_result = await router.generate_json(
            location=req.location,
            days=req.days,
            preferences=req.preferences or "",
            system_prompt=SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=0.3,
            step="generation",
        )
        gen_elapsed = int((time.perf_counter() - llm_start) * 1000)
        print(f"🎯 [travel-plan][step] generation finished: model={generation_result.model}, elapsed_ms={gen_elapsed}, input_tokens={generation_result.input_tokens}, output_tokens={generation_result.output_tokens}, cost_usd={generation_result.cost_usd:.6f}")

        print("🔍 [travel-plan][step] parsing generation JSON")
        parse_start = time.perf_counter()
        generation_obj = _extract_json_object(generation_result.content)
        parse_elapsed = int((time.perf_counter() - parse_start) * 1000)
        print(f"✨ [travel-plan][step] generation JSON valid={bool(generation_obj)}, elapsed_ms={parse_elapsed}")
        if not generation_obj:
            raise ValueError("LLM returned invalid JSON in generation step")
        if llm_debug_enabled:
            _print_llm_debug(
                "generation",
                prompt=user_prompt,
                raw_content=generation_result.content,
                parsed_obj=generation_obj,
            )

        final_obj = generation_obj
        if len(attractions) >= 8 and req.days >= 3:
            print("🧠 [travel-plan][step] LLM reflection start")
            reflection_prompt = _build_reflection_prompt(
                initial_plan_json=json.dumps(generation_obj, ensure_ascii=False),
                attractions_json=json.dumps(attractions, ensure_ascii=False),
            )
            reflect_start = time.perf_counter()
            reflection_result = await router.generate_json(
                location=req.location,
                days=req.days,
                preferences=req.preferences or "",
                system_prompt=SYSTEM_PROMPT,
                user_prompt=reflection_prompt,
                temperature=0.3,
                step="reflection",
            )
            reflect_elapsed = int((time.perf_counter() - reflect_start) * 1000)
            print(f"🎯 [travel-plan][step] reflection finished: model={reflection_result.model}, elapsed_ms={reflect_elapsed}, input_tokens={reflection_result.input_tokens}, output_tokens={reflection_result.output_tokens}, cost_usd={reflection_result.cost_usd:.6f}")

            print("🔍 [travel-plan][step] parsing reflection JSON")
            reflection_parse_start = time.perf_counter()
            reflection_obj = _extract_json_object(reflection_result.content)
            reflection_parse_elapsed = int((time.perf_counter() - reflection_parse_start) * 1000)
            print(f"✨ [travel-plan][step] reflection JSON valid={bool(reflection_obj)}, elapsed_ms={reflection_parse_elapsed}")
            if reflection_obj:
                final_obj = reflection_obj
                if llm_debug_enabled:
                    _print_llm_debug(
                        "reflection",
                        prompt=reflection_prompt,
                        raw_content=reflection_result.content,
                        parsed_obj=reflection_obj,
                    )
                    print(
                        "[travel-plan][llm-debug][optimization] "
                        f"generation_summary={json.dumps(_summarize_itinerary(generation_obj), ensure_ascii=False)}"
                    )
                    print(
                        "[travel-plan][llm-debug][optimization] "
                        f"reflection_summary={json.dumps(_summarize_itinerary(reflection_obj), ensure_ascii=False)}"
                    )
            else:
                print("[travel-plan][step] reflection invalid, fallback to generation result")
                if llm_debug_enabled:
                    print(
                        "[travel-plan][llm-debug][optimization] "
                        f"generation_summary={json.dumps(_summarize_itinerary(generation_obj), ensure_ascii=False)}"
                    )
        else:
            print("[travel-plan][step] reflection skipped due to small candidate set or short trip")
            if llm_debug_enabled:
                print(
                    "[travel-plan][llm-debug][optimization] "
                    f"generation_summary={json.dumps(_summarize_itinerary(generation_obj), ensure_ascii=False)}"
                )

        elapsed_ms = int((time.perf_counter() - started) * 1000)
        reflection_model = reflection_result.model if 'reflection_result' in locals() else 'skipped'
        reflection_cost = reflection_result.cost_usd if 'reflection_result' in locals() else 0.0
        print(f"[travel-plan][done] generation_model={generation_result.model}, reflection_model={reflection_model}, elapsed_ms={elapsed_ms}, generation_cost_usd={generation_result.cost_usd:.6f}, reflection_cost_usd={reflection_cost:.6f}")

        itinerary_raw = final_obj.get("itinerary") or []
        normalized_itinerary: List[Dict[str, Any]] = []
        meal_place_map = {str(m.get("name") or ""): m for m in meal_candidates}
        for day in itinerary_raw:
            if not isinstance(day, dict):
                continue
            activities = []
            for act in day.get("activities") or []:
                if not isinstance(act, dict):
                    continue
                ticket_price = act.get("ticket_price")
                if ticket_price in (None, ""):
                    matched_price = 0
                    act_name = str(act.get("name") or "")
                    for attraction in attractions:
                        if str(attraction.get("name") or "") == act_name:
                            matched_price = attraction.get("ticket_price", 0) or 0
                            break
                    ticket_price = matched_price
                activities.append({
                    **act,
                    "ticket_price": ticket_price,
                })
            meals: List[Dict[str, Any]] = []
            for meal in day.get("meals") or []:
                if not isinstance(meal, dict):
                    continue
                meal_name = str(meal.get("name") or "")
                source_meal = meal_place_map.get(meal_name)
                if source_meal:
                    meal = {
                        **meal,
                        "address": meal.get("address") or source_meal.get("address") or source_meal.get("formatted_address") or "",
                        "latitude": meal.get("latitude") if meal.get("latitude") is not None else source_meal.get("latitude"),
                        "longitude": meal.get("longitude") if meal.get("longitude") is not None else source_meal.get("longitude"),
                        "estimated_cost": meal.get("estimated_cost") or source_meal.get("estimated_cost") or 0,
                        "route_desc": meal.get("route_desc") or source_meal.get("route_desc") or source_meal.get("formatted_address") or "附近餐饮，步行可达",
                    }
                else:
                    meal = {
                        **meal,
                        "route_desc": meal.get("route_desc") or "附近餐饮，步行可达",
                    }
                meals.append({**meal})
            normalized_itinerary.append({**day, "activities": activities, "meals": meals})

        data = TravelPlanData(
            location=str(final_obj.get("location") or req.location),
            days=int(final_obj.get("days") or req.days),
            attractions=attractions,
            itinerary=normalized_itinerary,
            total_budget=final_obj.get("total_budget") or {"transport": 0, "tickets": 0, "food": 0, "total": 0, "currency": "EUR"},
            tips=[str(x) for x in (final_obj.get("tips") or []) if str(x).strip()],
            warnings=[str(x) for x in (final_obj.get("warnings") or []) if str(x).strip()],
        )
        return TravelPlanResponseV2(success=True, message="生成成功", data=data)
    except ValueError as e:
        print(f"[travel-plan][error] bad_request={e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        print(f"[travel-plan][error] {e}")
        raise HTTPException(status_code=500, detail=f"生成失败: {str(e)}")


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

            service = get_google_places_service()
            router = get_llm_router()
            yield _sse_event("progress", {"percent": 8, "status": "正在生成搜索策略..."})
            strategy_prompt = _build_search_strategy_prompt(req.location, req.days, req.preferences or "no special preference")
            strategy_result = await router.generate_json(location=req.location, days=req.days, preferences=req.preferences or "", system_prompt=SYSTEM_PROMPT, user_prompt=strategy_prompt, temperature=0.2, step="strategy")
            strategy_obj = _extract_json_object(strategy_result.content)
            yield _sse_event("step", {"name": "strategy", "status": "done", "description": "已生成搜索策略"})
            if llm_debug_enabled:
                yield _sse_event("llm_debug", {"stage": "strategy", "raw": strategy_result.content, "summary": _summarize_itinerary(strategy_obj)})

            attraction_queries = strategy_obj.get("attraction_queries") if isinstance(strategy_obj, dict) else None
            meal_queries = strategy_obj.get("meal_queries") if isinstance(strategy_obj, dict) else None
            if not isinstance(attraction_queries, list) or not attraction_queries:
                attraction_queries = [f"{req.location} 代表性景点 attractions", f"{req.location} 博物馆 历史景点"]
            if not isinstance(meal_queries, list) or not meal_queries:
                meal_queries = [f"{req.location} 早餐", f"{req.location} 午餐 餐厅", f"{req.location} 晚餐 餐厅"]

            yield _sse_event("progress", {"percent": 18, "status": "正在检索景点候选..."})
            raw_limit = _calc_candidate_limit(req.days)
            raw_attractions: List[Dict[str, Any]] = []
            for query in attraction_queries[:3]:
                try:
                    raw_attractions.extend(service.search_places(str(query), limit=raw_limit))
                    yield _sse_event("log", {"message": f"景点检索完成: {query}"})
                except Exception as attraction_exc:
                    yield _sse_event("log", {"message": f"景点检索失败: {query} / {attraction_exc}"})
            attractions = _normalize_attractions(raw_attractions)

            yield _sse_event("progress", {"percent": 32, "status": "正在检索餐饮候选..."})
            meal_candidates: List[Dict[str, Any]] = []
            meal_limit = min(max(req.days * 3, 6), 12)
            for meal_query in meal_queries[:3]:
                try:
                    meal_candidates.extend(service.search_places(str(meal_query), limit=max(2, meal_limit // 3)))
                    yield _sse_event("log", {"message": f"餐饮检索完成: {meal_query}"})
                except Exception as meal_exc:
                    yield _sse_event("log", {"message": f"餐饮检索失败: {meal_query} / {meal_exc}"})
            meal_candidates = meal_candidates[:meal_limit]

            yield _sse_event("progress", {"percent": 48, "status": "正在生成行程初稿..."})
            compact_attractions_json = json.dumps(_compact_attractions_for_llm(attractions[: _calc_candidate_limit(req.days)]), ensure_ascii=False)
            compact_meals_json = json.dumps(_compact_meals_for_llm(meal_candidates), ensure_ascii=False)
            user_prompt = _build_user_prompt(req.location, req.days, req.preferences or "no special preference", json.dumps(strategy_obj, ensure_ascii=False), compact_attractions_json, compact_meals_json)
            if llm_debug_enabled:
                yield _sse_event("llm_debug", {"stage": "generation_prompt", "prompt": _preview_text(user_prompt, max_chars=1800)})
            generation_result = await router.generate_json(location=req.location, days=req.days, preferences=req.preferences or "", system_prompt=SYSTEM_PROMPT, user_prompt=user_prompt, temperature=0.3, step="generation")
            generation_obj = _extract_json_object(generation_result.content)
            yield _sse_event("step", {"name": "generation", "status": "done", "description": "已生成初稿"})
            if llm_debug_enabled:
                yield _sse_event("llm_debug", {"stage": "generation", "raw": generation_result.content, "summary": _summarize_itinerary(generation_obj)})

            final_obj = generation_obj
            if len(attractions) >= 8 and req.days >= 3:
                yield _sse_event("progress", {"percent": 74, "status": "正在进行反思优化..."})
                reflection_prompt = _build_reflection_prompt(json.dumps(generation_obj, ensure_ascii=False), json.dumps(attractions, ensure_ascii=False))
                reflection_result = await router.generate_json(location=req.location, days=req.days, preferences=req.preferences or "", system_prompt=SYSTEM_PROMPT, user_prompt=reflection_prompt, temperature=0.3, step="reflection")
                reflection_obj = _extract_json_object(reflection_result.content)
                if reflection_obj:
                    final_obj = reflection_obj
                    yield _sse_event("step", {"name": "reflection", "status": "done", "description": "已完成反思优化"})
                    if llm_debug_enabled:
                        yield _sse_event("llm_debug", {"stage": "reflection", "raw": reflection_result.content, "summary": _summarize_itinerary(reflection_obj)})
                else:
                    yield _sse_event("log", {"message": "反思结果无效，已回退到初稿"})
            else:
                yield _sse_event("step", {"name": "reflection", "status": "skipped", "description": "候选较少，跳过反思"})

            itinerary_raw = final_obj.get("itinerary") or []
            normalized_itinerary: List[Dict[str, Any]] = []
            meal_place_map = {str(m.get("name") or ""): m for m in meal_candidates}
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
                meals: List[Dict[str, Any]] = []
                for meal in day.get("meals") or []:
                    if not isinstance(meal, dict):
                        continue
                    meal_name = str(meal.get("name") or "")
                    source_meal = meal_place_map.get(meal_name)
                    if source_meal:
                        meal = {**meal, "address": meal.get("address") or source_meal.get("address") or source_meal.get("formatted_address") or "", "latitude": meal.get("latitude") if meal.get("latitude") is not None else source_meal.get("latitude"), "longitude": meal.get("longitude") if meal.get("longitude") is not None else source_meal.get("longitude"), "estimated_cost": meal.get("estimated_cost") or source_meal.get("estimated_cost") or 0}
                    meals.append({**meal})
                normalized_itinerary.append({**day, "activities": activities, "meals": meals})

            data = TravelPlanData(
                location=str(final_obj.get("location") or req.location),
                days=int(final_obj.get("days") or req.days),
                attractions=attractions,
                itinerary=normalized_itinerary,
                total_budget=final_obj.get("total_budget") or {"transport": 0, "tickets": 0, "food": 0, "total": 0, "currency": "EUR"},
                tips=[str(x) for x in (final_obj.get("tips") or []) if str(x).strip()],
                warnings=[str(x) for x in (final_obj.get("warnings") or []) if str(x).strip()],
            )
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            yield _sse_event("progress", {"percent": 100, "status": "生成完成"})
            yield _sse_event("done", {"success": True, "message": "生成成功", "data": data.model_dump(), "elapsed_ms": elapsed_ms})
        except Exception as e:
            yield _sse_event("error", {"message": str(e)})

    return StreamingResponse(event_generator(), media_type="text/event-stream")
