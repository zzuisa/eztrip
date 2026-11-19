"""RogueTrip Google Places 旅行规划 API（LLM 直出 JSON）"""

from __future__ import annotations

import asyncio
import copy
from datetime import date, timedelta
import json
import math
import time
from textwrap import dedent
from typing import Any, Dict, List
import re

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from ...config import get_settings
from ...models.schemas import TravelPlanRequest, TravelPlanResponseV2, TravelPlanData, TripSegment
from ...services import multi_city
from ...services import weather as weather_svc
from ...services import journey
from ...services import voice
from ...services.google_places_service import get_google_places_service
from ...services.origin import clean_origin, origin_sentence
from ...services import transit_plan as transit_svc
from ...services.stay_plan import clean_stay, stay_sentence
from ...services import budget as budget_svc
from ...services.llm_service import get_llm_router
from ...services import place_search_orchestrator as pso
from ...services.travel_plan_store import get_travel_plan_store
from ...services.guest_guard import (
    client_ip,
    get_quota,
    is_owner,
    limits as guest_limits,
    require_owner,
)
from ...services.identity import can_edit as _can_edit, peek_user_key, set_cookie, user_key
from ...services.job_manager import get_job_manager
from ...services.poi_image_service import enrich_payload_images
# 纯行程/餐饮逻辑已下沉，供本流水线与 agents 共用（spec005）
from ...services.itinerary_utils import (
    _build_fallback_plan,
    _build_theme_fallbacks,
    _calc_candidate_limit,
    _compact_attractions_for_llm,
    _compact_meals_for_llm,
    _dedupe_by_name,
    _ensure_list,
    _extract_json_object,
    _is_citywalk_preference,
    _normalize_attractions,
    _normalize_day_title,
)
from ...services.meal_utils import (
    _collect_meals_near_anchors,
    _enforce_meal_quality_on_itinerary,
)

# SSE 心跳周期（秒）：长 LLM 调用期间用它保活，避免中间代理（Cloudflare ~100s）空闲超时。
HEARTBEAT_INTERVAL_SECONDS = 12.0


async def run_llm_with_heartbeats(coro, *, interval: float = HEARTBEAT_INTERVAL_SECONDS):
    """在等待某协程完成期间周期性产出心跳。

    产出序列：0 或多个 ``("ping", None)``，最后一个 ``("result", <值>)``。
    协程抛异常则透传（异常在此处 raise，由调用方处理）。
    """
    task = asyncio.ensure_future(coro)
    while True:
        done, _ = await asyncio.wait({task}, timeout=interval)
        if task in done:
            yield ("result", task.result())
            return
        yield ("ping", None)


def _sse_comment() -> str:
    """合法 SSE 注释行（以 ``:`` 开头），仅用于保活，客户端解析器会忽略。"""
    return ": keepalive\n\n"

router = APIRouter(prefix="/travel-plan", tags=["旅行规划"])

SYSTEM_PROMPT = """你是一位极度严谨、拥有强大空间规划和多国行程设计能力的欧洲旅行规划专家。
核心规则：
- 严格使用用户提供的 Google Places API 返回的景点数据，不得自行添加或删除景点。
- 所有空间分组、路线排序、交通方式选择、时间安排、预算分配等复杂规划任务，全部由你独立完成。
- 输出必须是纯 JSON，不允许任何额外文字。
- 季节与节假日判断以用户给出的出行日期为准。
""" + voice.VOICE_COPY

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
    3. 默认轻松自在：除非用户明确要求紧凑/特种兵，每天安排 3–4 个景点（不要超过 5 个），并包含早餐、午餐、晚餐；餐饮优先选择与偏好一致、且靠近当天景点路径的地点。
    4. 对于偏好相关的景点，请放入当天最重要的位置，并在 description / route_desc 中明确说明“为什么与偏好一致”。
    5. 如果用户偏好是预算、节奏、深度游、轻松游等，请把它体现在时间安排与 estimated_cost 中。
    6. 票价、地址、经纬度都要保留真实数据；无门票则 ticket_price=0。
    7. 所有景点的 `route_desc` 必须写成真实、具体、可执行的停留安排，禁止使用模板化的“第x站，建议停留 1-2 小时”。
    8. 每个景点的停留时间应根据景点属性、用户偏好和当天节奏动态安排，温泉/水疗至少 3.5 小时，博物馆/城堡/宫殿至少 2 小时，大教堂/公园/市场约 1 小时，观景台/桥/广场 30–45 分钟；景点之间留 15 分钟以上机动时间，宁可少排一个景点也不要压缩停留。
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
    - 每天标题应采用简洁说明式，例如“Day 1｜城堡山步行串联（老城地标+河景）”，天数前缀统一写成 Day N，不要写“第N天”，不要使用夸张词
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



def _refine_headline(ev: Dict[str, Any]) -> str:
    """审核—修订闭环的进度文案（给旧版进度条用）。"""
    st, n, t = ev.get("stage"), ev.get("round"), ev.get("total")
    if st == "review_start":
        return "正在检查行程…"
    if st == "review_done":
        k = len([i for i in ev.get("issues") or [] if i.get("severity") != "low"])
        return "正在优化行程…" if k else "行程检查通过"
    if st == "revise_start":
        return "正在优化行程…"
    if st == "revise_done":
        return "调整完成，准备复审"
    if st == "final":
        return "行程已完成最终检查"
    return "质量审核中…"


async def _agent_event_generator(req: TravelPlanRequest, final: bool = True):
    """PLANNING_MODE=agent：多 Agent 编排（spec005）。

    Queue + emit 模式（对齐 StockPilot `api/agent.py`）：supervisor/composer 在后台任务里跑，
    这里把它们 emit 的事件转成 SSE。事件类型 `phase|delta|day`，
    同时**映射一份既有的 `progress`/`done`** 以兼容尚未升级的前端。
    """
    from ...agents.runner import run_agent_planning

    q: asyncio.Queue = asyncio.Queue()

    async def emit(ev: Dict[str, Any]) -> None:
        await q.put(ev)

    task = asyncio.create_task(run_agent_planning(
        location=req.location, days=req.days,
        preferences=req.preferences or "", origin=clean_origin(req.origin), emit=emit,
        start_date=req.start_date or "", transportation=req.transportation or "", stay_name=clean_stay(req.stay_name), weather_report=getattr(req, "weather_context", None),
        trip_meta=_trip_meta(req) if final else None))

    _log_stage("agent", f"start location={req.location}, days={req.days}")
    yield _sse_event("progress", {"percent": 2, "status": "启动多 Agent 规划..."})
    pct = 5
    try:
        while True:
            if task.done() and q.empty():
                break
            try:
                ev = await asyncio.wait_for(q.get(), timeout=HEARTBEAT_INTERVAL_SECONDS)
            except asyncio.TimeoutError:
                yield _sse_comment()          # 长工具/LLM 期间保活（防 CF 524）
                continue

            etype = str(ev.get("type") or "phase")
            yield _sse_event(etype, ev)       # 新协议：phase | delta | day

            # 兼容旧前端：把 agent 事件映射成既有 progress/log
            if etype == "phase":
                pct = min(92, pct + 3)
                yield _sse_event("progress", {
                    "percent": pct,
                    "status": str(ev.get("detail") or ev.get("agent") or "处理中..."),
                })
            elif etype == "day":
                pct = min(95, pct + 4)
                yield _sse_event("progress", {"percent": pct, "status": f"Day {ev.get('day')} 已生成"})
            elif etype == "refine":
                pct = min(96, pct + 1)
                yield _sse_event("progress", {"percent": pct, "status": _refine_headline(ev)})

        if task.exception():
            raise task.exception()

        payload = task.result()
        _log_stage("agent", f"done elapsed_ms={payload.get('elapsed_ms')}")
        yield _sse_event("progress", {"percent": 100, "status": "生成完成"})
        yield _sse_event("result", {"success": True, "data": payload})
        yield _sse_event("done", {
            "success": True, "message": "生成成功", "data": payload,
            "result_id": payload.get("result_id"), "elapsed_ms": payload.get("elapsed_ms"),
        })
    except Exception as e:                     # noqa: BLE001
        _log_stage("agent", f"error type={type(e).__name__}, error={e}")
        yield _sse_event("error", {"message": str(e), "detail": repr(e)})
    finally:
        if not task.done():
            task.cancel()


async def _multi_city_generator(req: TravelPlanRequest, segs: List[Dict[str, Any]], make_generator):
    """多城市串联：逐站跑单城市生成，进度按站折算；各站的结果合并成一份行程后再保存。"""
    started = time.perf_counter()
    store = get_travel_plan_store()
    n = len(segs)
    results: List[Dict[str, Any]] = []
    sub_ids: List[str] = []
    yield _sse_event("progress", {"percent": 1, "status": "正在规划 %d 座城市的串联行程..." % n})
    try:
        for i, seg in enumerate(segs):
            sub = req.model_copy(update={
                "location": seg["city"], "days": seg["days"], "segments": None,
                "stays": [s.model_copy(update={'night': s.night - sum(x['days'] for x in segs[:i])}) for s in req.stays if sum(x['days'] for x in segs[:i]) < s.night <= sum(x['days'] for x in segs[:i+1])],
                "day_windows": [w.model_copy(update={'day': w.day - sum(x['days'] for x in segs[:i])}) for w in req.day_windows if sum(x['days'] for x in segs[:i]) < w.day <= sum(x['days'] for x in segs[:i+1])],
                "origin": (segs[i - 1]["city"] if i else req.origin), "origin_lat": (None if i else req.origin_lat),
                "origin_lng": (None if i else req.origin_lng),
                "stay_name": None, "stay_lat": None, "stay_lng": None,
                "destination_lat": req.destination_lat if i == 0 else None, "destination_lng": req.destination_lng if i == 0 else None,
                "start_date": (( date.fromisoformat(req.start_date) + timedelta(days=sum(x['days'] for x in segs[:i]))).isoformat() if req.start_date else None),
                "end_date": None,
            })
            continuation = '' if i == n - 1 else f'；这是串联行程的中间一站，结束后继续前往「{clean_origin(segs[i + 1]["city"])}」，不要在这里返回出发地。'
            sub = sub.model_copy(update={'preferences': (sub.preferences or '') + journey.constraints(sub, include_return=i == n - 1) + continuation})
            gen = make_generator(sub, False)      # 中间站不单独最终化：合并后整体 settle + 审核
            got = None
            lo, hi = 2 + 94 * i / n, 2 + 94 * (i + 1) / n
            try:
                async for chunk in gen:
                    if chunk.startswith(":"):
                        yield chunk
                    elif chunk.startswith("event: progress"):
                        try:
                            body = json.loads(chunk.partition("data:")[2].strip())
                            pct = float(body.get("percent") or 0)
                            yield _sse_event("progress", {"percent": int(lo + (hi - lo) * min(pct, 100) / 100), "status": "【%s】%s" % (seg["city"], body.get("status") or "")})
                        except Exception:
                            pass
                    elif chunk.startswith("event: refine") or chunk.startswith("event: phase"):
                        try:  # 审核闭环 / 阶段事件：带上城市后原样转给前端
                            kind = chunk.partition("event:")[2].partition("\n")[0].strip()
                            body = json.loads(chunk.partition("data:")[2].strip())
                            yield _sse_event(kind, {**body, "city": seg["city"], "segment": i})
                        except Exception:
                            pass
                    elif chunk.startswith("event: done"):
                        got = json.loads(chunk.partition("data:")[2].strip())
                    elif chunk.startswith("event: error"):
                        yield chunk
                        return
            finally:
                await gen.aclose()
            data = (got or {}).get("data") if isinstance(got, dict) else None
            if not isinstance(data, dict) or not data.get("itinerary"):
                yield _sse_event("error", {"message": "【%s】这一站没有生成出行程，请稍后重试" % seg["city"]})
                return
            if got.get("result_id"):
                sub_ids.append(str(got["result_id"]))
            results.append(data)
        merged = multi_city.merge(results, segs)
        result_id = store.save(merged)
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        yield _sse_event("progress", {"percent": 98, "status": "正在衔接各城市之间的交通..."})
        yield _sse_event("done", {"success": True, "message": "生成成功", "data": {**merged, "result_id": result_id}, "result_id": result_id, "elapsed_ms": elapsed_ms})
    finally:
        for sid in sub_ids:  # 各站的中间结果只用于合并，不留在"我的行程"里
            try:
                store.delete(sid)
            except Exception:
                pass


@router.post(
    "/stream",
    summary="Google Places 旅行规划流式输出",
    description="以 SSE 方式实时返回进度、阶段描述和最终结果。",
)
async def generate_travel_plan_stream(req: TravelPlanRequest, request: Request):
    # Keep user intent separate from generated route constraints mentioning walking.
    weather_preferences = '/'.join(filter(None, [req.preferences, req.transportation]))
    async def event_generator(req: TravelPlanRequest = req):
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
            strategy_result = None
            async for _kind, _val in run_llm_with_heartbeats(
                router.generate_json(location=req.location, days=req.days, preferences=req.preferences or "", system_prompt=SYSTEM_PROMPT+weather_svc.planning_block(getattr(req, "weather_context", None)), user_prompt=strategy_prompt, temperature=0.2, step="strategy")
            ):
                if _kind == "ping":
                    yield _sse_comment()
                else:
                    strategy_result = _val
            strategy_elapsed = int((time.perf_counter() - strategy_start) * 1000)
            _log_stage("strategy", f"llm_done model={strategy_result.model}, elapsed_ms={strategy_elapsed}, input_tokens={strategy_result.input_tokens}, output_tokens={strategy_result.output_tokens}, cost_usd={strategy_result.cost_usd:.6f}")
            strategy_obj = _extract_json_object(strategy_result.content)
            _log_stage("strategy", f"json_parsed valid={bool(strategy_obj)}, keys={list(strategy_obj.keys()) if isinstance(strategy_obj, dict) else []}")
            yield _sse_event("step", {"name": "strategy", "status": "done", "description": "已生成搜索策略"})
            if llm_debug_enabled:
                strategy_debug = _build_llm_debug_payload("strategy", prompt=strategy_prompt, raw_content=strategy_result.content, parsed_obj=strategy_obj)
                _log_llm_debug("strategy", strategy_debug)
                yield _sse_event("llm_debug", strategy_debug)
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
                yield _sse_event("progress", {"percent": 18, "status": "正在按天主题并发检索候选..."})
                per_query_limit = max(5, min((raw_limit // 2) if citywalk_mode else (raw_limit // 3), 10))
                # 预处理每天的查询（保持 strategy 给定的天顺序）
                day_plans: List[Dict[str, Any]] = []
                for theme_day in strategy_daily_themes:
                    if not isinstance(theme_day, dict):
                        continue
                    day_index = int(theme_day.get("day") or 0)
                    theme = str(theme_day.get("theme") or f"Day {day_index}")
                    theme_tags = _ensure_list(theme_day.get("theme_tags"))
                    a_queries = _ensure_list(theme_day.get("attraction_queries"))
                    m_queries = _ensure_list(theme_day.get("meal_queries"))
                    if not a_queries or not m_queries:
                        a_queries, m_queries = _build_theme_fallbacks(req.location, day_index, theme, theme_tags, req.preferences or "")
                    day_plans.append({
                        "day_index": day_index,
                        "theme": theme,
                        "theme_tags": theme_tags,
                        "attraction_queries": list(a_queries[:4]),
                        "meal_queries": list(m_queries[:3]),
                    })

                # 阶段 A：一次性并发所有天的景点查询（有界并发 + 请求内去重）
                all_attraction_queries = [q for dp in day_plans for q in dp["attraction_queries"]]
                search_start = time.perf_counter()
                attraction_results = await pso.search_texts(service, all_attraction_queries, limit=per_query_limit)
                _log_stage("daily_theme.attraction", f"parallel_done unique_queries={len(set(str(q).strip() for q in all_attraction_queries))}, elapsed_ms={int((time.perf_counter() - search_start) * 1000)}")
                yield _sse_comment()

                day_attractions_map: Dict[int, List[Dict[str, Any]]] = {}
                for dp in day_plans:
                    day_raw: List[Dict[str, Any]] = []
                    for query in dp["attraction_queries"]:
                        items = attraction_results.get(str(query).strip(), [])
                        day_raw.extend(items)
                        raw_attractions.extend(items)
                    day_attractions_map[dp["day_index"]] = _normalize_attractions(day_raw)[:8]

                # 阶段 B：跨天并发餐饮检索（每天内部仍串行，天之间并发，受信号量限流）
                yield _sse_event("progress", {"percent": 34, "status": "正在并发检索餐饮候选..."})
                meal_sem = asyncio.Semaphore(4)
                meal_start = time.perf_counter()

                async def _collect_day(dp: Dict[str, Any]):
                    async with meal_sem:
                        return await asyncio.to_thread(
                            _collect_meals_near_anchors,
                            service,
                            location=req.location,
                            day_index=dp["day_index"],
                            meal_queries=dp["meal_queries"],
                            day_attractions=day_attractions_map[dp["day_index"]],
                        )

                meal_results = await asyncio.gather(*[_collect_day(dp) for dp in day_plans])
                _log_stage("daily_theme.meal", f"parallel_done days={len(day_plans)}, elapsed_ms={int((time.perf_counter() - meal_start) * 1000)}")
                yield _sse_comment()

                for dp, (day_meals, day_meal_source, day_meal_stats) in zip(day_plans, meal_results):
                    day_index = dp["day_index"]
                    day_attractions = day_attractions_map[day_index]
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
                        "theme": dp["theme"],
                        "theme_tags": dp["theme_tags"],
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
                        items = await asyncio.to_thread(service.search_places, str(query), raw_limit)
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
                day_meals, day_meal_source, day_meal_stats = await asyncio.to_thread(
                    _collect_meals_near_anchors,
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
            user_prompt = _build_user_prompt(req.location, req.days, (req.preferences or "no special preference") + origin_sentence(req.origin) + stay_sentence(req.stay_name, req.stay_lat, req.stay_lng), json.dumps({**strategy_obj, "daily_buckets": daily_buckets}, ensure_ascii=False), compact_attractions_json, compact_meals_json, daily_buckets_json)
            _log_stage("generation", f"prompt_built chars={len(user_prompt)}")
            if llm_debug_enabled:
                _print_llm_debug("generation_prompt", prompt=user_prompt, raw_content="", parsed_obj={})
                yield _sse_event("llm_debug", {"stage": "generation_prompt", "prompt": _preview_text(user_prompt, max_chars=1800), "attractions_count": len(attractions), "meal_candidates_count": len(meal_candidates)})
            if not daily_buckets:
                _log_stage("generation", "daily_buckets_empty_using_compact_candidates_only")
            generation_start = time.perf_counter()
            generation_result = None
            try:
                # Token 流式：generation 期间实时推进度，消除静默 + 抗超时（spec 004）
                gen_chars = 0
                last_emit = time.perf_counter()
                async for _kind, _val in router.generate_json_stream(location=req.location, days=req.days, preferences=req.preferences or "", system_prompt=SYSTEM_PROMPT+weather_svc.planning_block(getattr(req, "weather_context", None)), user_prompt=user_prompt, temperature=0.2, step="generation"):
                    if _kind == "delta":
                        gen_chars += len(_val)
                        now = time.perf_counter()
                        if now - last_emit >= 1.5:
                            last_emit = now
                            yield _sse_event("progress", {"percent": min(70, 48 + gen_chars // 200), "status": f"正在生成行程...(已 {gen_chars} 字)"})
                    else:
                        generation_result = _val
            except Exception as stream_exc:
                # 流式失败（provider 拒绝/断流）→ 回退非流式，仍保 spec 003 行为
                _log_stage("generation", f"stream_failed_fallback_non_stream error={stream_exc}")
                yield _sse_comment()
                generation_result = None
                async for _kind, _val in run_llm_with_heartbeats(
                    router.generate_json(location=req.location, days=req.days, preferences=req.preferences or "", system_prompt=SYSTEM_PROMPT+weather_svc.planning_block(getattr(req, "weather_context", None)), user_prompt=user_prompt, temperature=0.2, step="generation")
                ):
                    if _kind == "ping":
                        yield _sse_comment()
                    else:
                        generation_result = _val
            generation_elapsed = int((time.perf_counter() - generation_start) * 1000)
            _log_stage("generation", f"llm_done model={generation_result.model}, elapsed_ms={generation_elapsed}, input_tokens={generation_result.input_tokens}, output_tokens={generation_result.output_tokens}, cost_usd={generation_result.cost_usd:.6f}")
            generation_obj = _extract_json_object(generation_result.content)
            _log_stage("generation", f"json_parsed valid={bool(generation_obj)}, keys={list(generation_obj.keys()) if isinstance(generation_obj, dict) else []}")
            if not generation_obj:
                _log_stage("generation", "json_invalid_retry_with_stricter_prompt")
                retry_prompt = user_prompt + "\n\n强制要求：只能输出合法 JSON，不允许任何思考、解释、markdown、代码块、附加文本；如果候选不足，只能缩短行程或返回空数组，不得编造。"
                retry_start = time.perf_counter()
                retry_result = None
                async for _kind, _val in run_llm_with_heartbeats(
                    router.generate_json(location=req.location, days=req.days, preferences=req.preferences or "", system_prompt=SYSTEM_PROMPT+weather_svc.planning_block(getattr(req, "weather_context", None)), user_prompt=retry_prompt, temperature=0.0, step="generation_retry")
                ):
                    if _kind == "ping":
                        yield _sse_comment()
                    else:
                        retry_result = _val
                retry_elapsed = int((time.perf_counter() - retry_start) * 1000)
                _log_stage("generation_retry", f"llm_done model={retry_result.model}, elapsed_ms={retry_elapsed}, input_tokens={retry_result.input_tokens}, output_tokens={retry_result.output_tokens}, cost_usd={retry_result.cost_usd:.6f}")
                generation_obj = _extract_json_object(retry_result.content)
                _log_stage("generation_retry", f"json_parsed valid={bool(generation_obj)}, keys={list(generation_obj.keys()) if isinstance(generation_obj, dict) else []}")
                if llm_debug_enabled:
                    _print_llm_debug("generation_retry", prompt=retry_prompt, raw_content=retry_result.content, parsed_obj=generation_obj)
            if not generation_obj:
                generation_warnings = ["行程已按可用地点为您稳妥编排，可随时调整任意一站。"]
                generation_obj = _build_fallback_plan(req.location, req.days, daily_buckets, attractions, meal_candidates, generation_warnings)
                _log_stage("generation", f"fallback_plan_built days={len(generation_obj.get('itinerary', []))}")
            yield _sse_event("step", {"name": "generation", "status": "done", "description": "已生成初稿"})
            if llm_debug_enabled:
                _print_llm_debug("generation", prompt=user_prompt, raw_content=generation_result.content, parsed_obj=generation_obj)
                yield _sse_event("llm_debug", {"stage": "generation", "raw": generation_result.content, "summary": _summarize_itinerary(generation_obj), "prompt": _preview_text(user_prompt, max_chars=1800)})

            # reflection 段已下线：generation 直出为最终结果（generation prompt 已含充分约束）。
            final_obj = voice.scrub_value(generation_obj)

            final_obj.setdefault("warnings", [])
            if isinstance(final_obj.get("warnings"), list) and generation_warnings:
                final_obj["warnings"] = list(dict.fromkeys([*final_obj.get("warnings", []), *generation_warnings]))
            yield _sse_event("progress", {"percent": 82, "status": "正在校验餐饮就近性..."})
            itinerary_raw = _ensure_list(final_obj.get("itinerary"))
            itinerary_raw, meal_validation_metrics = await asyncio.to_thread(
                _enforce_meal_quality_on_itinerary,
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
                    act_name = str(act.get("name") or "")
                    source_attraction = None
                    for attraction in attractions:
                        if str(attraction.get("name") or "") == act_name:
                            source_attraction = attraction
                            break
                    ticket_price = act.get("ticket_price")
                    if ticket_price in (None, ""):
                        ticket_price = source_attraction.get("ticket_price", 0) if source_attraction else 0
                    image_url = act.get("image_url") or act.get("photo_url") or act.get("thumbnail") or act.get("image")
                    if not image_url and source_attraction:
                        image_url = source_attraction.get("image_url") or source_attraction.get("photo_url") or source_attraction.get("thumbnail") or source_attraction.get("image")
                    activities.append({
                        **act,
                        # 强制约束：LLM 可能返回 null，这些是 schema 必填 string/float，需兜底
                        "name": str(act.get("name") or ""),
                        "time": str(act.get("time") or ""),
                        "description": str(act.get("description") or ""),
                        "route_desc": str(act.get("route_desc") or ""),
                        "estimated_cost": float(act.get("estimated_cost") or 0),
                        "ticket_price": ticket_price,
                        "image_url": image_url,
                        "photo_url": act.get("photo_url") or image_url,
                        "thumbnail": act.get("thumbnail") or image_url,
                        "image": act.get("image") or image_url,
                        "preference_matched": bool(act.get("preference_matched")),
                        "preference_reason": str(act.get("preference_reason") or ""),
                    })
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
                    meals.append({
                        **meal,
                        # schema 必填 string/float 兜底，防 LLM null
                        "type": str(meal.get("type") or "snack"),
                        "name": str(meal.get("name") or ""),
                        "time": str(meal.get("time") or ""),
                        "description": str(meal.get("description") or ""),
                        "route_desc": str(meal.get("route_desc") or ""),
                        "estimated_cost": float(meal.get("estimated_cost") or 0),
                    })
                day_no = int(day.get("day") or (len(normalized_itinerary) + 1))
                normalized_title = _normalize_day_title(day_no, str(day.get("title") or ""), str(day.get("route_summary") or ""))
                normalized_itinerary.append({**day, "day": day_no, "title": normalized_title, "route_summary": str(day.get("route_summary") or ""), "activities": activities, "meals": meals})

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
            _log_stage("done", f"elapsed_ms={elapsed_ms}, generation_cost_usd={generation_result.cost_usd:.6f}")
            yield _sse_event("progress", {"percent": 100, "status": "生成完成"})
            yield _sse_event("done", {"success": True, "message": "生成成功", "data": {**saved_payload, "result_id": result_id}, "result_id": result_id, "elapsed_ms": elapsed_ms})
        except Exception as e:
            _log_stage("error", f"type={type(e).__name__}, error={e}")
            yield _sse_event("error", {"message": str(e), "detail": repr(e)})

    # PLANNING_MODE 分流：agent=spec005 多 Agent 编排；其余=spec004 流水线（默认，稳）
    mode = str(getattr(get_settings(), "planning_mode", "pipeline") or "pipeline").lower()
    async def make_generator(r: TravelPlanRequest, final: bool = True):
        from ...services import experiences
        from ...services import dining
        r=r.model_copy(update={'preferences':dining.prompt(r.dining.model_dump())+'\n'+experiences.prompt(r.experience.model_dump())+'\n'+(r.preferences or '')})
        yield _sse_event("progress", {"percent": 1, "status": "正在核对目的地日期与天气..."})
        report = await asyncio.to_thread(weather_svc.for_plan, r.location, r.start_date or '', r.days,
                                        weather_preferences, r.destination_lat, r.destination_lng)
        r = r.model_copy(update={'weather_context': report})
        gen = _agent_event_generator(r, final) if mode == 'agent' else event_generator(r)
        try:
            async for chunk in gen:
                if chunk.startswith(('event: done', 'event: result')):
                    body = json.loads(chunk.partition('data:')[2].strip())
                    if isinstance(body.get('data'), dict):
                        weather_svc.attach(body['data'], report)
                        if chunk.startswith('event: done') and body.get('result_id'):
                            get_travel_plan_store().merge_payload(body['result_id'], {
                                'weather': report, 'weather_info': body['data']['weather_info'], 'warnings': body['data']['warnings']})
                        chunk = _sse_event('done' if chunk.startswith('event: done') else 'result', body)
                yield chunk
        finally:
            await gen.aclose()

    segs = multi_city.normalize_segments(req.segments, req.days)
    if len(segs) >= 2:
        req = req.model_copy(update={"segments": [TripSegment(**s) for s in segs], "days": sum(s["days"] for s in segs),
                                     "location": " → ".join(s["city"] for s in segs), "stay_name": None, "stay_lat": None, "stay_lng": None})
        generator = _multi_city_generator(req, segs, make_generator)
    else:
        req = req.model_copy(update={'preferences': (req.preferences or '') + journey.constraints(req)})
        # 主题引导：用户在生成前选的“深度 / 主题+精华 / 精华一览”→ 一句约束，追加进 preferences（策略 / 检索 / 编排统一遵循）
        from ...services import discover as discover_service
        _fs = discover_service.focus_sentence(req.focus, req.days)
        if _fs:
            req = req.model_copy(update={"preferences": ((req.preferences or "").strip() + _fs)[:900]})
        generator = make_generator(req)

    # 范围太宽泛（洲/模糊词/多目的地）：不烧额度，直接让前端二次提问
    from ...services import scope as scope_service
    if len(segs) >= 2:
        _scope = next((x for x in (scope_service.assess(s["city"], s["days"]) for s in segs) if scope_service.is_hard_block(x)), {"level": "ok"})
    else:
        _scope = scope_service.assess(req.location, req.days)
    if scope_service.is_hard_block(_scope):
        await generator.aclose()
        raise HTTPException(status_code=422, detail={"code": "scope_unclear", "message": _scope.get("question") or "目的地范围太大", "scope": _scope})

    # 游客限额与并发保护；站长（Basic 凭据与 htpasswd 匹配）放行
    ip = client_ip(request)
    owner = is_owner(request)
    manager = get_job_manager()
    lim = guest_limits()
    if manager.running_count() >= lim["running"]:
        await generator.aclose()
        raise HTTPException(status_code=429, detail={"code": "server_busy", "message": "当前规划任务较多，请稍后再试"}, headers={"Retry-After": "30"})
    counted = False
    units = max(1, len(segs))  # 多城市串联每一站算一次生成额度
    if not owner:
        took = 0
        try:
            for _ in range(units):
                get_quota().consume("gen", ip, lim["gen"])
                took += 1
        except HTTPException:
            for _ in range(took):
                get_quota().refund("gen", ip)
            await generator.aclose()
            raise
        counted = True
    uk, new_uid = user_key(request)
    generator = _attach_trip_meta(generator, req, uk)
    job = manager.start(generator, ip, counted, on_guest_failure=lambda: [get_quota().refund("gen", ip) for _ in range(units)])
    resp = StreamingResponse(job.follow(0), media_type="text/event-stream", headers=_SSE_HEADERS)
    set_cookie(resp, request, new_uid)
    return resp


_ENRICHING: set = set()
_BG_TASKS: set = set()


def _spawn(coro) -> None:
    task = asyncio.create_task(coro)
    _BG_TASKS.add(task)
    task.add_done_callback(_BG_TASKS.discard)


def _payload_missing_images(payload: Dict[str, Any]) -> bool:
    for day in payload.get("itinerary") or []:
        if not isinstance(day, dict):
            continue
        for it in list(day.get("activities") or []) + list(day.get("meals") or []):
            if isinstance(it, dict) and it.get("name") and not it.get("image_url"):
                return True
    return False


async def _enrich_result_images(result_id: str) -> None:
    """后台给已保存结果补图（景点/餐饮），不阻塞响应；同一结果同时只跑一个。"""
    if not result_id or result_id in _ENRICHING:
        return
    _ENRICHING.add(result_id)
    try:
        store = get_travel_plan_store()
        record = store.get(result_id)
        if not record:
            return
        # 在副本上解析（耗时、不持锁），再在锁内把 image_url 并回最新 payload
        import copy
        work = copy.deepcopy(record.get("payload") or {})
        await asyncio.to_thread(enrich_payload_images, work)

        def merge(latest: Dict[str, Any]) -> bool:
            def copy_urls(src_items, dst_items):
                for s_it, d_it in zip(src_items or [], dst_items or []):
                    if isinstance(s_it, dict) and isinstance(d_it, dict) and s_it.get("name") == d_it.get("name") and s_it.get("image_url") and not d_it.get("image_url"):
                        for k in ("image_url", "photo_url", "thumbnail", "image"):
                            d_it[k] = s_it[k]
            copy_urls(work.get("attractions"), latest.get("attractions"))
            for sd, ld in zip(work.get("itinerary") or [], latest.get("itinerary") or []):
                if isinstance(sd, dict) and isinstance(ld, dict):
                    copy_urls(sd.get("activities"), ld.get("activities"))
                    copy_urls(sd.get("meals"), ld.get("meals"))
            return True

        store.update_payload(result_id, merge)
        _log_stage("images", f"enriched result_id={result_id}")
    except Exception as e:  # noqa: BLE001
        _log_stage("images", f"enrich failed result_id={result_id}: {type(e).__name__}: {e}")
    finally:
        _ENRICHING.discard(result_id)


def _trip_meta(req: TravelPlanRequest) -> Dict[str, Any]:
    """行程元信息（日期/交通/住宿/出发地/租车/每日窗口…）：规划（最终化）与保存共用同一份。"""
    meta = {
        k: v
        for k, v in {
            "start_date": req.start_date,
            "end_date": req.end_date,
            "transportation": req.transportation,
            "accommodation": req.accommodation,
            "origin": clean_origin(req.origin),
            "origin_lat": req.origin_lat if clean_origin(req.origin) else None,
            "origin_lng": req.origin_lng if clean_origin(req.origin) else None,
            "stay_name": clean_stay(req.stay_name),
            "stay_lat": req.stay_lat if clean_stay(req.stay_name) else None,
            "stay_lng": req.stay_lng if clean_stay(req.stay_name) else None,
        }.items()
        if v is not None and v != ''
    }
    meta.update(journey.metadata(req))
    return meta


def _carry_over(old: List[Any], new: List[Any]) -> None:
    """把后台补上的图片等字段按名字带到新的一天里（时间/地点以 new 为准）。"""
    for day_new, day_old in zip(new or [], old or []):
        if not (isinstance(day_new, dict) and isinstance(day_old, dict)):
            continue
        for key in ("activities", "meals"):
            by_name = {str(x.get("name")): x for x in day_old.get(key) or [] if isinstance(x, dict)}
            for it in day_new.get(key) or []:
                src = by_name.get(str(it.get("name"))) if isinstance(it, dict) else None
                if src:
                    for k, v in src.items():
                        it.setdefault(k, v)


async def _attach_trip_meta(generator, req: TravelPlanRequest, editor: str = ""):
    """在 done 事件里附带行程元信息，并保证“交付的行程 = 被审核过的行程”。

    - agent 流水线（单城市）已在内部 settle + 审核，这里只附加元信息；
    - 其余（旧流水线 / 多城市合并）：先 settle（到达/取还车/返程/窗口排定）+ 算预算，再做最终审核；
    - 任何路径出口都有指纹守卫：行程指纹 ≠ 审核指纹就重审（见 agents/final_review.py）。
    """
    from ...agents import final_review
    from ...agents import reviewer as reviewer_mod
    from ...services import finalize

    meta = _trip_meta(req)
    try:
        async for chunk in generator:
            if chunk.startswith("event: done"):
                try:
                    _rid = json.loads(chunk.partition("data:")[2].strip()).get("result_id")
                    if _rid:
                        _spawn(_enrich_result_images(_rid))
                        if editor:  # 记录生成者（匿名 uid / owner），决定谁能编辑；存记录顶层，不随 GET 返回
                            get_travel_plan_store().update_record(_rid, lambda r: r.__setitem__("editor", editor))
                        if (req.preferences or "").strip():
                            # 偏好随结果保存，供地点对话作为上下文（不放进 trip_meta，避免被结果页当作元信息渲染）
                            _pref = req.preferences.strip()[:300]
                            get_travel_plan_store().update_payload(_rid, lambda p: p.update({"request_preferences": _pref}))
                except Exception:
                    pass
            if chunk.startswith("event: done"):
                try:
                    body = json.loads(chunk.partition("data:")[2].strip())
                    rid = body.get("result_id")
                    data = body.get("data")
                    if rid and meta:
                        get_travel_plan_store().merge_payload(rid, {"trip_meta": meta})
                    if isinstance(data, dict) and meta:
                        data["trip_meta"] = meta
                    if isinstance(data, dict) and data.get("itinerary"):
                        if not data.get("settled"):
                            yield _sse_event("progress", {"percent": 98, "status": "正在按到达、取还车与返程时间排定行程..."})
                            try:
                                before = copy.deepcopy(data.get("itinerary") or [])
                                info = finalize.settle(data, meta, fit=True)
                                data["tips"] = list(dict.fromkeys([*(data.get("tips") or []), *info["notes"]]))
                                data["warnings"] = list(dict.fromkeys([*(data.get("warnings") or []), *[c["message"] for c in info["checks"]]]))
                                yield _sse_event("progress", {"percent": 99, "status": "正在核对交通与住宿价格..."})
                                data["total_budget"] = await budget_svc.build_budget(data, meta, adapt=False)
                                data["settled"] = True
                                data["fingerprint"] = finalize.fingerprint(data)
                                if rid:
                                    def _persist(p, _d=data, _before=before):
                                        _carry_over(p.get("itinerary") or [], _d["itinerary"])
                                        for k in ("itinerary", "total_budget", "tips", "warnings", "settled", "fingerprint"):
                                            p[k] = _d[k]
                                    get_travel_plan_store().update_payload(rid, _persist)
                            except Exception as be:  # noqa: BLE001
                                _log_stage("settle", f"failed {type(be).__name__}: {be}")
                        # 出口守卫：审核必须发生在最终数据之后
                        if final_review.needs_review(data):
                            yield _sse_event("progress", {"percent": 99, "status": "正在对最终行程做最后审核..."})
                            review = await final_review.review_payload(data, meta, source="final")
                            final_review.apply_review(data, review)
                            if rid:
                                def _persist_review(p, _d=data):
                                    for k in ("review", "fingerprint", "warnings", "check_warnings", "tips"):
                                        if k in _d:
                                            p[k] = _d[k]
                                get_travel_plan_store().update_payload(rid, _persist_review)
                    chunk = _sse_event("done", body)
                except Exception as exc:  # noqa: BLE001
                    _log_stage("final", f"failed {type(exc).__name__}: {exc}")
            yield chunk
    finally:
        await generator.aclose()


_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    # 禁止 nginx 缓冲 SSE，保证心跳/事件即时下发（配合 nginx proxy_buffering off）
    "X-Accel-Buffering": "no",
}


def _get_job_or_404(job_id: str):
    job = get_job_manager().get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail={"code": "job_not_found", "message": "任务不存在或已过期"})
    return job


@router.get("/jobs/{job_id}", summary="查询规划任务状态")
async def get_travel_plan_job(job_id: str):
    return {"success": True, **_get_job_or_404(job_id).snapshot()}


@router.get("/jobs/{job_id}/events", summary="续看规划任务事件流（SSE，from 为已接收事件数）")
async def follow_travel_plan_job(job_id: str, start: int = 0):
    job = _get_job_or_404(job_id)
    return StreamingResponse(job.follow(max(start, 0)), media_type="text/event-stream", headers=_SSE_HEADERS)


@router.delete("/jobs/{job_id}", summary="取消规划任务")
async def cancel_travel_plan_job(job_id: str):
    job = _get_job_or_404(job_id)
    cancelled = get_job_manager().cancel(job_id)
    return {"success": True, "cancelled": cancelled, "status": job.status}


@router.get(
    "/results",
    summary="获取旅行规划记录列表（站长：全部；游客：自己生成的）",
)
async def list_travel_plan_results(request: Request, limit: int = 100):
    store = get_travel_plan_store()
    limit = max(1, min(int(limit), 200))
    if is_owner(request):
        return {"success": True, "scope": "all", "items": store.list(limit=limit)}
    me = peek_user_key(request)
    return {"success": True, "scope": "mine", "items": store.list(limit=limit, editor=me) if me else []}


@router.get(
    "/results/{result_id}",
    summary="获取单个旅行规划记录",
)
async def get_travel_plan_result(result_id: str, request: Request):
    store = get_travel_plan_store()
    record = store.get(result_id)
    if not record:
        raise HTTPException(status_code=404, detail="记录不存在")
    payload = dict(record.get("payload") or {})
    weather_svc.compact_presentation(payload)
    from ...services import budget as budget_svc
    from ...services.transit_plan import present_transport
    present_transport(payload)
    budget_svc.present_legacy(payload)
    if _payload_missing_images(payload):
        _spawn(_enrich_result_images(result_id))  # 旧结果自愈：后台补图并持久化
    # 审核必须对应“当前这一份”行程：指纹对不上（旧行程 / 编辑后审核尚未完成）→ 标记过期；能编辑的人读取时顺手重审
    from ...agents import final_review
    stale = final_review.needs_review(payload)
    if stale and _can_edit(request, record):
        _spawn(final_review.review_stored(result_id, source="refresh"))
    return {
        "success": True,
        "id": result_id,
        "created_at": record.get("created_at"),
        "updated_at": record.get("updated_at"),
        "data": {**payload, "result_id": result_id, "review_stale": stale},
        "rev": int(record.get("rev") or 0),
        "can_edit": _can_edit(request, record),
        "edited": bool(record.get("original")),
    }


@router.delete(
    "/results/{result_id}",
    summary="删除单个旅行规划记录（站长，或该行程的生成者）",
)
async def delete_travel_plan_result(result_id: str, request: Request):
    store = get_travel_plan_store()
    rec = store.get(result_id)
    if rec and not (is_owner(request) or (rec.get("editor") and rec.get("editor") == peek_user_key(request))):
        raise HTTPException(status_code=403, detail={"code": "owner_required", "message": "只能删除自己生成的行程"})
    ok = store.delete(result_id)
    if not ok:
        raise HTTPException(status_code=404, detail="记录不存在")
    return {"success": True, "id": result_id}
