"""Supervisor Agent：动态委派的多 Agent 编排（对齐 StockPilot 的 `run_supervisor`）。

tool-calling 循环：把能力总线（含 xhs_insight / poi_scout / food_scout 三个子 Agent）交给
**专用 tool 模型**，让它自主决定调哪个、调几次；全程 `emit` 流式推 `phase` 事件。

**边界（关键）**：supervisor **只做调研与策展**，产出「按天候选池」，
**绝不产出行程 JSON**——严格 JSON 由 `composer.py` 按天并发生成（spec005 research.md 的设计分水岭）。
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

from ..services.llm_service import get_llm_router
from ..agent_config import model as configured_model, prompt as configured_prompt
from ..tools import dispatch, specs
from . import context as ctx_mod
from .context import PlanningContext
from ..services.weather import planning_block

log = logging.getLogger(__name__)

MAX_ROUNDS = 8

_SYSTEM = """你是旅行规划的总调度（supervisor），统筹多个专精子 Agent 为用户**收集并策展**行程候选池。

你有这些工具：
- xhs_insight(theme)：小红书灵感（当地推荐/避坑/候选地名）。**候选地名没有坐标，不能直接用**。
- poi_scout(day, queries)：为某天检索景点候选（Google Places，真实坐标）。**这是景点的唯一可信来源**。
- food_scout(day, meal_queries)：为某天就近检索餐饮（必须先对该天做过 poi_scout）。
- search_places / search_places_near_anchor：底层检索（一般用不到，优先用上面的子 Agent）。

工作流程（必须遵守）：
1. 先调 xhs_insight 拿灵感（若返回 available=false 就直接跳过，**不要重试**）。
2. 为**每一天**规划一个清晰主题，然后对**每一天**调用 poi_scout（把该天主题相关的检索词、
   以及 xhs_insight 给的候选地名，一起作为 queries 传入以校验坐标）。
3. 候选不能全部是博物馆/教堂/古迹；按用户游玩结构加入当地生活、手作、演出、温泉或季节项目的检索词，保留真实坐标；季节开放不能猜测。然后对**每一天**调用 food_scout。
4. 全部天都完成后，用一段简短中文说明你的策展思路（每天主题 + 为什么这样选），然后**结束**。

铁律：
- **不要输出任何行程 JSON**，不要排时间表——那是下游 composer 的工作。你只负责把候选池备齐。
- 每天都必须调用一次 poi_scout 和一次 food_scout，一天都不能漏。
- 工具返回的只是摘要（数量/名字），完整数据已存服务端，你不需要也不要复述它们。
"""


def _arg_hint(args: Dict[str, Any]) -> str:
    for k in ("day", "theme", "keyword"):
        if k in args:
            return f"{k}={args[k]}"
    return ""


async def run_supervisor(ctx: PlanningContext) -> Dict[str, Any]:
    """跑一次 supervisor 策展。候选池写进 ctx，返回 {summary, tool_calls}。"""
    ctx_mod.set_context(ctx)
    router = get_llm_router()

    await ctx_mod.emit({"type": "phase", "agent": "supervisor", "status": "running",
                        "detail": "规划委派方案"})

    tool_specs = specs(risk={"read"})
    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": configured_prompt("supervisor", _SYSTEM)},
        {"role": "user", "content":
            f"目的地：{ctx.location}\n天数：{ctx.days} 天\n用户偏好：{ctx.preferences or '无特别偏好'}\n\n"
            + planning_block(ctx.weather) + f"请按流程为这 {ctx.days} 天备齐候选池。"},
    ]

    tool_calls_log: List[Dict[str, Any]] = []
    summary = ""

    for round_no in range(MAX_ROUNDS):
        try:
            msg = await router.chat_with_tools(messages, tool_specs, temperature=0.2,
                model=configured_model("supervisor", router.settings.llm_model_tool))
        except Exception as e:                   # noqa: BLE001
            log.warning("supervisor tool 循环失败(round %s): %s", round_no, e)
            await ctx_mod.emit({"type": "phase", "agent": "supervisor", "status": "error",
                                "detail": f"调度失败：{e}"})
            break

        calls = msg.get("tool_calls") or []
        if not calls:
            summary = str(msg.get("content") or "").strip()
            break

        messages.append({"role": "assistant", "content": msg.get("content") or "",
                         "tool_calls": calls})

        for c in calls:
            fn = (c.get("function") or {})
            name = fn.get("name") or ""
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except Exception:
                args = {}

            await ctx_mod.emit({"type": "phase", "agent": name, "status": "running",
                                "detail": f"委派 {name}({_arg_hint(args)})"})
            out = await dispatch(name, args)
            tool_calls_log.append({"tool": name, "args": args})

            messages.append({"role": "tool", "tool_call_id": c.get("id"),
                             "content": json.dumps(out, ensure_ascii=False, default=str)[:2000]})

    # 兜底：某些天没被 supervisor 覆盖到 → 用确定性检索补齐，保证 composer 有料可用
    await _backfill_missing_days(ctx)

    await ctx_mod.emit({"type": "phase", "agent": "supervisor", "status": "done",
                        "detail": f"策展完成：{len(ctx.attractions_by_day)} 天候选就绪"})
    if summary:
        await ctx_mod.emit({"type": "delta", "agent": "supervisor", "text": summary})

    return {"summary": summary, "tool_calls": tool_calls_log}


async def _backfill_missing_days(ctx: PlanningContext) -> None:
    """supervisor 可能漏调某天（LLM 不可靠）→ 用确定性回退补齐，绝不让 composer 面对空候选池。"""
    from ..services.itinerary_utils import _build_theme_fallbacks

    for day in range(1, ctx.days + 1):
        if not ctx.attractions_by_day.get(day):
            log.info("supervisor 漏了第 %s 天的景点 → 回退补齐", day)
            a_queries, m_queries = _build_theme_fallbacks(
                ctx.location, day, "", [], ctx.preferences or "")
            weather_days = ctx.weather.get('days') or []
            if day <= len(weather_days) and weather_days[day-1].get('risk') in ('high', 'moderate'):
                a_queries = [f"{ctx.location} 室内当地体验 手作 水疗 文化场所", *a_queries]
            await dispatch("poi_scout", {"day": day, "queries": a_queries[:4]})
        if not ctx.meals_by_day.get(day) and ctx.attractions_by_day.get(day):
            log.info("supervisor 漏了第 %s 天的餐饮 → 回退补齐", day)
            await dispatch("food_scout", {"day": day})
