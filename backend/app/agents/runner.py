"""Agent 模式的规划入口：supervisor（策展）→ composer（按天并发出 JSON）→ 校验落库。

被 `api/routes/travel_plan.py` 的 `/stream` 在 `PLANNING_MODE=agent` 时调用。
把编排逻辑收在这里，路由只负责 SSE 传输（职责分离，宪法 VIII）。
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable, Dict, List, Optional

from ..models.schemas import TravelPlanData
from ..services.google_places_service import get_google_places_service
from ..services.itinerary_utils import _dedupe_by_name, _ensure_list
from ..services.meal_utils import _enforce_meal_quality_on_itinerary
from ..services.travel_plan_store import get_travel_plan_store
from . import context as ctx_mod
from ..services.day_geo import filter_attractions, sanitize_itinerary
from ..services.llm_service import get_llm_router
from ..services.model_config import get_model
from . import reviewer
from .composer import _sum_budget, compose, recompose_day  # noqa: F401  (recompose_day 供测试替换)
from .refine import refine_plan
from ..services import voice
from . import feasibility, polish          # noqa: F401
from . import refine as refine_mod
from ..services import finalize
from .context import PlanningContext
from .supervisor import run_supervisor

log = logging.getLogger(__name__)


async def run_agent_planning(
    *,
    location: str,
    days: int,
    preferences: str = "",
    origin: str = "",
    emit: Optional[Callable] = None,
    start_date: str = "",
    transportation: str = "",
    stay_name: str = "",
    weather_report: Optional[Dict[str, Any]] = None,
    trip_meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """跑一次多 Agent 规划。返回 {**payload, result_id, elapsed_ms}。"""
    started = time.perf_counter()
    ctx = PlanningContext(location=location, days=days, preferences=preferences or "", origin=origin or "", emit=emit,
                          start_date=start_date or "", transportation=transportation or "", stay_name=stay_name or "")
    ctx.weather = weather_report or {}
    ctx.trip_meta = trip_meta          # None = 多城市中间站：不最终化，由合并后的整体统一最终化 + 审核
    ctx_mod.set_context(ctx)

    # 1) supervisor 策展候选池（内部会 emit phase 事件）
    await run_supervisor(ctx)

    from ..services import experiences
    await experiences.research(ctx,get_google_places_service())

    # 1.5) 偏好里点名的地点（如温泉）必须进候选池并被排进行程
    try:
        from . import musthave
        picks = await musthave.ensure_preference_picks(ctx, get_google_places_service())
        if picks:
            log.info('must_include: %s', picks)
    except Exception as e:                       # noqa: BLE001
        log.warning('偏好必选项保障失败（跳过）: %s', e)

    # 2) composer 按天并发出严格 JSON（每天 emit 一个 day 事件）
    plan = await compose(ctx)

    # 3) 餐饮就近校验（复用旧流水线逻辑；同步 → 丢线程池）
    service = get_google_places_service()
    itinerary = _ensure_list(plan.get("itinerary"))
    try:
        itinerary, metrics = await asyncio.to_thread(
            _enforce_meal_quality_on_itinerary,
            service=service,
            location=location,
            itinerary=itinerary,
            daily_meal_sources=ctx.meal_sources,
        )
        plan["itinerary"] = itinerary
        log.info("meal_quality: %s", metrics)
    except Exception as e:                       # noqa: BLE001 —— 校验失败不该让整单失败
        log.warning("餐饮就近校验失败（跳过）: %s", e)

    # 3.5) 地理合理性：剔除离群点 / 占位餐饮，生成真实 warnings（不再悄悄交付散乱行程）
    geo_warnings: List[str] = []
    try:
        itinerary, geo_warnings, geo_stats = sanitize_itinerary(_ensure_list(plan.get("itinerary")))
        plan["itinerary"] = itinerary
        plan["attractions"] = filter_attractions(_ensure_list(plan.get("attractions")), itinerary)
        plan["total_budget"] = _sum_budget(itinerary, days)
        log.info("day_geo: %s", {k: v for k, v in geo_stats.items() if k != "centers"})
    except Exception as e:                       # noqa: BLE001
        log.warning("地理校验失败（跳过）: %s", e)
    # 3.6) 最终化 + 审核—修订闭环（critic，默认 combo/main）：
    #      [润色 → settle(到达/取还车/返程/窗口) → 审核] → 带着意见与硬约束重排 → [润色 → settle → 复审]
    #      审核永远基于最终数据；交付的就是被审核过的那一份，此后不再有任何改动行程的步骤。
    review: Optional[Dict[str, Any]] = None
    if reviewer.should_review(days):
        itinerary, geo_warnings, review = await refine_plan(ctx, plan, itinerary, geo_warnings, service, location, days, preferences, origin)
    else:
        refine_mod.settle_only(ctx, plan, itinerary)
    itinerary = _ensure_list(plan.get("itinerary"))
    plan["review"] = reviewer.public_view(review)
    plan["tips"] = list(dict.fromkeys([*[str(x) for x in _ensure_list(plan.get("tips")) if str(x).strip()], *reviewer.to_tips(review)]))
    # 程序已经自动处理掉的事（顺延、移除放不下的、换天…）是“已为你调整”的说明，不是待办提醒
    adjustments = [*[str(x) for x in _ensure_list(plan.get("settle_notes"))], *geo_warnings]
    plan["tips"] = list(dict.fromkeys([*plan["tips"], *adjustments]))
    # 只有“排定之后仍然无法满足”的硬问题 + 营业时间未解决项 + 候选不足，才作为提醒；审核意见留在 review 记录里，不甩给用户
    geo_warnings = [*[str(x) for x in _ensure_list(plan.get("hard_checks"))], *list(ctx.hours_issues)]
    for d in sorted(ctx.fallback_days):
        geo_warnings.append(f"Day {d}：已优先保证路线顺畅；如想增加更多去处，可点“调整这一站”继续补充")
    plan["warnings"] = list(dict.fromkeys([*geo_warnings, *[str(x) for x in _ensure_list(plan.get("warnings")) if str(x).strip()]]))
    plan.pop("settle_notes", None)
    plan.pop("hard_checks", None)

    # 3.8) 预算：只读行程（重建同一份交通、查价格），不改行程；若指纹变了说明有人动了行程 → 下游守卫会重新审核
    if trip_meta is not None:
        try:
            from ..services import budget as budget_svc
            before = finalize.fingerprint(plan)
            plan["total_budget"] = await budget_svc.build_budget(plan, trip_meta, adapt=False)
            plan["itinerary"] = _ensure_list(plan.get("itinerary"))
            if finalize.fingerprint(plan) != before:
                log.warning("预算计算改动了行程指纹：审核结果将被判定为过期并重审")
        except Exception as e:                    # noqa: BLE001 —— 预算失败不影响交付，保留粗算
            log.warning("预算计算失败（保留粗算）: %s", e)

    # 3.9) 话术出口：统一成专业顾问的口吻（剔除“信息较少，建议查看官网”之类套话）
    plan["itinerary"] = voice.scrub_value(_ensure_list(plan.get("itinerary")))
    plan["tips"] = voice.scrub_value([str(x) for x in _ensure_list(plan.get("tips"))])
    plan["warnings"] = voice.scrub_value([str(x) for x in _ensure_list(plan.get("warnings"))])

    from ..services.xhs_research import attach as attach_xhs
    attach_xhs(plan,ctx)

    # 4) 严格校验 + 落库
    data = TravelPlanData(
        location=str(plan.get("location") or location),
        days=int(plan.get("days") or days),
        attractions=_dedupe_by_name(_ensure_list(plan.get("attractions"))),
        itinerary=_ensure_list(plan.get("itinerary")),
        total_budget=plan.get("total_budget") or {
            "transport": 0, "tickets": 0, "food": 0, "total": 0, "currency": "EUR"},
        tips=[str(x) for x in _ensure_list(plan.get("tips")) if str(x).strip()],
        warnings=[str(x) for x in _ensure_list(plan.get("warnings")) if str(x).strip()],
        review=plan.get("review"),
    )
    payload = data.model_dump()
    payload['experience_research']=ctx.experience
    payload['xhs_research']=plan.get('xhs_research',{})
    if ctx.experience.get('optional_venues'):
        payload.setdefault('tips',[]).append('部分季节或场次体验尚未核实出行日开放，保留为候选，没有强行排入。')
    elif ctx.experience.get('status') in ('unavailable','no_verified_venues'):
        payload.setdefault('tips',[]).append('当地体验开放资料暂未充分核实，未强行安排季节项目，可在地点详情继续核对。')
    if review and review.get('quality_gate'):payload['planning_status']=review['quality_gate']['state']
    from ..services import weather
    weather.attach(payload, ctx.weather)
    # TravelPlanDay 模型不含 transit_*：把 settle 排好的首/末交通原样写回落库的行程（否则要靠下游补，补就等于审核后改动）
    from ..services import transit_plan as transit_svc
    transit_svc.copy_transits(_ensure_list(plan.get("itinerary")), payload.get("itinerary") or [])
    payload["fingerprint"] = finalize.fingerprint(payload)
    if trip_meta is not None:
        payload["settled"] = True                              # 已按最终数据排定并审核；下游不要再改行程
        if isinstance(payload.get("review"), dict) and payload["review"].get("fingerprint") not in (None, payload["fingerprint"]):
            log.warning("落库后行程指纹与审核指纹不一致：将由下游守卫重新审核")
    result_id = get_travel_plan_store().save(payload)
    elapsed_ms = int((time.perf_counter() - started) * 1000)

    log.info("agent planning done: days=%s elapsed_ms=%s", days, elapsed_ms)
    return {**payload, "result_id": result_id, "elapsed_ms": elapsed_ms}
