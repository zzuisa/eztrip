"""Composer：把 supervisor 策展出的候选池编成严格 `TravelPlanData` JSON —— **按天并发**。

为什么单独一层（spec005 的设计分水岭）：
tool-loop 的自然产物是「散文 + 工具调用」，让 supervisor 同时维持一份数千 token 的严格 JSON
极不可靠（spec003 就被 LLM 的 `description: null` 崩过）。所以 Agent 只策展，JSON 由这里出。

按天并发的一致性风险，**全部用代码兜住，不依赖 LLM 自觉**：
1. `assign_days()`：全局按 place_id/name 去重后分配到天 —— 同一个点**不可能**出现在两天。
2. 每天只编排**自己那一天**（输出从 ~4500 token 降到 ~1500），`Semaphore` 限流并发。
3. `total_budget` **由代码求和**，不让 LLM 算总账（避免各天口径不一）。
4. 单天 JSON 非法 → **该天单独兜底**，不拖垮其它天。
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
from typing import Any, Dict, List

from ..services.origin import origin_block
from ..services.pace import pace_block
from .musthave import must_block
from ..services.stay_plan import stay_block
from ..services.itinerary_utils import (
    _build_fallback_day_plan,
    _compact_attractions_for_llm,
    _compact_meals_for_llm,
    _dedupe_by_name,
    _ensure_list,
    _extract_json_object,
    coerce_day,
)
from ..services.llm_service import get_llm_router
from ..services import voice
from ..agent_config import model as configured_model, prompt as configured_prompt
from . import context as ctx_mod
from .context import PlanningContext
from ..services.weather import planning_block

log = logging.getLogger(__name__)

DAY_CONCURRENCY = 3

_DAY_SYSTEM = (
    "你是严谨的旅行行程编排专家。只能使用给定候选池中的景点与餐饮，"
    "禁止编造任何不存在的地点、地址或经纬度。输出必须是纯 JSON，不允许任何额外文字。\n"
    + voice.VOICE_COPY
)

_DAY_TEMPLATE = """请为「{location}」的**第 {day} 天**编排一份可执行的单日行程。

当天主题：{theme}
用户偏好：{preferences}
{origin_block}{insight_block}
当天景点候选（**只能从这里选**，坐标/地址必须原样保留）：
{attractions_json}

当天餐饮候选（**只能从这里选**）：
{meals_json}

编排要求：
- 从景点候选里挑 3-4 个（用户明确要紧凑时可更多；citywalk 类偏好可到 5-6 个），按**真实地理顺序**串成一条可步行/公交的路线。
- 每个景点给出 `time`（如 09:00-10:30）与 `route_desc`（真实、具体的交通与停留安排，禁止套话）。
- 停留时长**不得短于**候选里的 `suggested_stay_minutes`（它已是轻松节奏下的值），可以更长，不要压缩。
- 安排早/午/晚三餐，**必须**从餐饮候选里选，且尽量靠近当天路线。
- `ticket_price` 用候选里的真实值；无门票写 0。`estimated_cost` 给合理的中档估算。
- 与用户偏好高度相关的活动，标 `preference_matched=true` 并在 `preference_reason` 一句话说明。
- 标题 `title` 克制、信息化（说明区域/主题/节奏），不要夸张营销词。

只输出如下 JSON（不要任何解释）：
{{
  "day": {day},
  "title": "string",
  "route_summary": "string",
  "activities": [
    {{"name":"string","time":"09:00-10:30","description":"string","route_desc":"string",
      "estimated_cost":0,"ticket_price":0,"address":"string","latitude":0,"longitude":0,
      "preference_matched":false,"preference_reason":"string"}}
  ],
  "meals": [
    {{"type":"breakfast","name":"string","time":"08:00-08:40","description":"string",
      "route_desc":"string","estimated_cost":0,"address":"string","latitude":0,"longitude":0,
      "place_id":"string"}}
  ]
}}
"""


# ── 精简 prompt 变体（给本地/小参数 thinking 模型用）────────────────────────
#
# 为什么需要它（实测踩坑）：`qwen3.5:9b`（Ollama）面对上面那个长模板会**陷入思维链死循环**——
# reasoning 狂写 6 万字、content 始终为空、顶满 max_tokens。`think:false` /`/no_think` /
# `chat_template_kwargs.enable_thinking=false` / 去掉 response_format 全都救不回来。
# 但换成下面这个精简版，同一个模型 24s 就能稳定吐出可解析的单天 JSON。
# → 结论：小参数 thinking 模型的 prompt 必须短、规则少、schema 小。
# 由 `LLM_LEAN_PROMPTS` 开关控制，不影响 DeepSeek 等强模型走原模板。

_DAY_SYSTEM_LEAN = "你是行程编排助手。只输出 JSON，不要任何解释。"

_DAY_TEMPLATE_LEAN = """为{location}第{day}天编排行程（主题：{theme}；偏好：{preferences}）。
{origin_block}**只能**使用下面给的景点和餐厅，坐标/地址原样保留，不要编造。

景点候选：
{attractions_json}

餐厅候选：
{meals_json}

要求：挑 3-5 个景点按地理顺序串成路线；配早/午/晚三餐；给出时间段；无门票写 0。

只输出如下 JSON：
{{"day":{day},"title":"标题","route_summary":"当天路线摘要",
"activities":[{{"name":"","time":"09:00-10:30","description":"","route_desc":"","estimated_cost":0,"ticket_price":0,"address":"","latitude":0,"longitude":0}}],
"meals":[{{"type":"breakfast","name":"","time":"08:00-08:40","description":"","route_desc":"","estimated_cost":0,"address":"","latitude":0,"longitude":0,"place_id":""}}]}}
"""


def _use_lean() -> bool:
    from ..config import get_settings
    return bool(getattr(get_settings(), "llm_lean_prompts", False))


def _place_key(item: Dict[str, Any]) -> str:
    return str(item.get("place_id") or "").strip() or str(item.get("name") or "").strip().lower()


MIN_PER_DAY = 3
MAX_PER_DAY = 8


def assign_days(ctx: PlanningContext) -> Dict[int, List[Dict[str, Any]]]:
    """**纯代码**跨天去重 + **均衡**分配：每个景点只归一天，且没有一天被饿死。

    这是按天并发能成立的前提——从根上消除「同一景点出现在多天」的风险，不依赖 LLM 自觉。

    为什么要均衡（踩过的坑）：若各天的检索结果高度重合（例如 supervisor 失败走了回退、
    各天用了相同查询），单纯「先到先得」会让第 1 天吃光整个候选池，后面几天拿到 0 个。
    所以：先按每天上限 `cap` 取自己那天的候选，溢出的再补给**当前最少的天**。
    """
    days = max(1, int(ctx.days))
    seen: set[str] = set()
    pool: List[tuple[int, Dict[str, Any]]] = []   # (原本属于哪天, 景点)
    for day in range(1, days + 1):
        for item in ctx.attractions_by_day.get(day, []) or []:
            key = _place_key(item)
            if not key or key in seen:
                continue
            seen.add(key)
            pool.append((day, item))

    assigned: Dict[int, List[Dict[str, Any]]] = {d: [] for d in range(1, days + 1)}
    if not pool:
        return assigned

    cap = max(MIN_PER_DAY, min(MAX_PER_DAY, math.ceil(len(pool) / days)))

    leftovers: List[Dict[str, Any]] = []
    for pref_day, item in pool:
        if len(assigned[pref_day]) < cap:
            assigned[pref_day].append(item)
        else:
            leftovers.append(item)

    # 溢出的补给"当前候选最少的天"，保证均衡、没有空天
    for item in leftovers:
        target = min(range(1, days + 1), key=lambda d: len(assigned[d]))
        if len(assigned[target]) >= MAX_PER_DAY:
            break
        assigned[target].append(item)

    return assigned


MIN_ACTIVITIES = 3
MEAL_SLOTS = ("breakfast", "lunch", "dinner")
_DEFAULT_MEAL_TIME = {"breakfast": "08:00-08:40", "lunch": "12:00-13:00", "dinner": "18:30-19:30"}


def ensure_day_completeness(day_plan: Dict[str, Any], day: int,
                            attractions: List[Dict[str, Any]],
                            ctx: PlanningContext) -> Dict[str, Any]:
    """LLM 少写活动 / 漏餐时，用**代码**从候选池补齐。

    实测踩坑：小模型（qwen2.5:14b）指令遵从性不稳——明明要求「3-5 个景点 + 三餐」，
    某天只吐了 1 个活动 1 顿饭（输出才 377 token，并非被截断，是它自己提前收尾）。
    与其祈祷模型自觉，不如按本项目一贯做法：**代码兜底补齐**。
    """
    from ..services import experiences
    priorities=[a for a in attractions if a.get('experience_priority')]
    # Half-day experiences are valid sparse days; don't fill them with three museums.
    minimum=1 if any(int(a.get('suggested_stay_minutes') or 0)>=180 for a in priorities) else MIN_ACTIVITIES
    # ── 按体验时长补活动 ──
    acts = _ensure_list(day_plan.get("activities"))
    used = {str(a.get("name") or "").strip().lower() for a in acts}
    for attr in attractions:
        if len(acts) >= minimum:
            break
        name = str(attr.get("name") or "").strip()
        if not name or name.lower() in used:
            continue
        used.add(name.lower())
        hour = min(9 + len(acts) * 2, 19)
        acts.append({
            "name": name,
            "time": f"{hour:02d}:00-{min(hour + 1, 20):02d}:30",
            "description": attr.get("editorial_summary") or f"{name}，今日路线中的推荐停留点。",
            "route_desc": "按当天路线顺序前往，注意控制步行距离。",
            "estimated_cost": 0,
            "ticket_price": float(attr.get("ticket_price") or 0),
            "address": attr.get("formatted_address") or "",
            "latitude": attr.get("lat"),
            "longitude": attr.get("lng"),
        })
    # 用户偏好点名的必选地点（如温泉）：模型没排进去就由代码补上（时间交给 polish 顺延、拉长）
    for attr in attractions:
        name = str(attr.get("name") or "").strip()
        if attr.get("must_include") and name and name.lower() not in {str(a.get("name") or "").strip().lower() for a in acts}:
            acts.append({
                "name": name, "time": "10:30-14:00",
                "description": attr.get("editorial_summary") or f"{name}，您在偏好里特别提到的目的地。",
                "route_desc": "偏好点名要去的地方，预留充足时间，不赶行程。",
                "estimated_cost": 0, "ticket_price": float(attr.get("ticket_price") or 0),
                "address": attr.get("formatted_address") or "", "latitude": attr.get("lat"), "longitude": attr.get("lng"),
                "preference_matched": True, "preference_reason": "你的偏好里提到了它",
            })
    # The real, source-backed experience candidate must remain available to composition.
    for attr in priorities[:1]:
        if attr['name'].casefold() not in {str(a.get('name','')).casefold() for a in acts}:
            if len(acts)>=minimum:
                victim=next((i for i,a in reversed(list(enumerate(acts))) if experiences.museum(a)),None)
                if victim is not None:acts.pop(victim)
            duration=int(attr.get('suggested_stay_minutes') or 90)
            acts.append({'name':attr['name'],'time':f"14:00-{14+duration//60:02d}:{duration%60:02d}",
                         'description':attr.get('editorial_summary') or '', 'route_desc':'按实际路线衔接并预留往返、休息与预约时间',
                         'estimated_cost':0,'ticket_price':float(attr.get('ticket_price') or 0),
                         'address':attr.get('formatted_address') or '', 'latitude':attr.get('lat'),'longitude':attr.get('lng')})
    day_plan["activities"] = acts
    experiences.enrich_day(day_plan,attractions,ctx.preferences)

    # ── 补齐早/午/晚三餐 ──
    meals = _ensure_list(day_plan.get("meals"))
    have = {str(m.get("type") or "").strip().lower() for m in meals}
    used_meal = {str(m.get("name") or "").strip().lower() for m in meals}
    source = ctx.meal_sources.get(day) or {}
    by_type = source.get("by_type") or {}
    pool_all = ctx.meals_by_day.get(day) or []

    for slot in MEAL_SLOTS:
        if slot in have:
            continue
        for cand in (_ensure_list(by_type.get(slot)) + list(pool_all)):
            name = str(cand.get("name") or "").strip()
            if not name or name.lower() in used_meal:
                continue
            used_meal.add(name.lower())
            meals.append({
                "type": slot,
                "name": name,
                "time": _DEFAULT_MEAL_TIME[slot],
                "description": cand.get("description") or "",
                "route_desc": "就近安排在当天路线附近。",
                "estimated_cost": float(cand.get("estimated_cost") or 0),
                "address": cand.get("address") or "",
                "latitude": cand.get("latitude"),
                "longitude": cand.get("longitude"),
                "place_id": cand.get("place_id") or "",
            })
            break
    day_plan["meals"] = meals
    return day_plan


def _insight_block(ctx: PlanningContext) -> str:
    ins = ctx.insight or {}
    if not ins.get("available") or not ins.get("highlights"):
        return ""
    lines = "\n".join(f"- {h}" for h in ins.get("highlights", [])[:5])
    avoid = ins.get("avoid") or []
    block = f"\n小红书灵感（可参考，但**地点仍只能从下面候选池里选**）：\n{lines}\n"
    if avoid:
        block += "避坑提醒：" + "；".join(str(a) for a in avoid[:3]) + "\n"
    return block


async def _compose_one_day(ctx: PlanningContext, day: int, attractions: List[Dict[str, Any]],
                           sem: asyncio.Semaphore) -> Dict[str, Any]:
    """编排单天。失败 → 该天兜底，不抛错（不拖垮其它天）。"""
    from ..services.experiences import prompt as experience_prompt, policy
    meals = ctx.meals_by_day.get(day, []) or []
    theme = (ctx.day_themes.get(day) or {}).get("theme") or "综合游览"

    # 注意：即便候选为空也**必须**走到底部的 coerce + emit day，
    # 否则前端收不到该天的事件（提前 return 会静默吞掉一天）。
    if not attractions:
        log.warning("第 %s 天没有景点候选 → 兜底", day)
        ctx.fallback_days.add(day)
        day_plan = coerce_day(_build_fallback_day_plan(day - 1, theme, [], [], meals), day)
        await ctx_mod.emit({"type": "day", "day": day, "data": day_plan})
        await ctx_mod.emit({"type": "phase", "agent": "composer", "status": "done",
                            "detail": f"Day {day}：候选不足，已生成保守安排"})
        return day_plan

    fb = ctx.review_feedback.get(day)
    async with sem:
        await ctx_mod.emit({"type": "phase", "agent": "composer", "status": "running",
                            "detail": (f"Day {day}：按审核意见重新编排" if fb else f"Day {day}：编排行程（{len(attractions)} 景点 / {len(meals)} 餐饮）")})
        lean = _use_lean()
        fb_block = ("\n审核意见（上一版编排存在以下问题，本次必须修正）：" + fb + "\n") if fb else ""
        if lean:
            # 小模型：精简 prompt + 收窄候选（喂太多候选同样会诱发思维链发散）
            system_prompt = configured_prompt("formatter", _DAY_SYSTEM_LEAN) + planning_block(ctx.weather, day)
            user_prompt = _DAY_TEMPLATE_LEAN.format(
                location=ctx.location, day=day, theme=theme,
                preferences=ctx.preferences or "无特别偏好",
                origin_block=origin_block(ctx.origin, ctx.location, day, ctx.days) + stay_block(ctx.stay_name, day, ctx.days) + pace_block(ctx.preferences) + must_block(attractions) + fb_block,
                attractions_json=json.dumps(
                    _compact_attractions_for_llm(attractions, max_items=6), ensure_ascii=False),
                meals_json=json.dumps(
                    _compact_meals_for_llm(meals, max_items=6), ensure_ascii=False),
            )
        else:
            system_prompt = configured_prompt("formatter", _DAY_SYSTEM) + planning_block(ctx.weather, day)
            user_prompt = _DAY_TEMPLATE.format(
                location=ctx.location,
                day=day,
                theme=theme,
                preferences=ctx.preferences or "无特别偏好",
                origin_block=origin_block(ctx.origin, ctx.location, day, ctx.days) + stay_block(ctx.stay_name, day, ctx.days) + pace_block(ctx.preferences) + must_block(attractions),
                insight_block=_insight_block(ctx) + fb_block,
                attractions_json=json.dumps(attractions, ensure_ascii=False),
                meals_json=json.dumps(_compact_meals_for_llm(meals, max_items=9), ensure_ascii=False),
            )
        from ..services.xhs_research import prompt_block
        user_prompt += prompt_block(ctx)
        system_prompt+='\n'+experience_prompt(policy(ctx.preferences))+'\n候选中的体验时长和季节确认条件必须保留；半天项目只安排1–2项，不机械凑3–4个景点。'
        router = get_llm_router()
        obj: Dict[str, Any] = {}
        try:
            result = None
            async for kind, val in router.generate_json_stream(
                    location=ctx.location, days=ctx.days, preferences=ctx.preferences or "",
                    system_prompt=system_prompt, user_prompt=user_prompt,
                    temperature=0.2, step=f"compose_day{day}",
                    model=(ctx.revise_model if (fb and ctx.revise_model) else configured_model("formatter", router.primary_model))):
                if kind == "result":
                    result = val
            obj = _extract_json_object(result.content) if result else {}
        except Exception as e:                   # noqa: BLE001
            log.warning("第 %s 天编排失败: %s", day, e)
            obj = {}

    if not obj or not _ensure_list(obj.get("activities")):
        log.warning("第 %s 天 JSON 无效/为空 → 兜底", day)
        ctx.fallback_days.add(day)
        day_plan = _build_fallback_day_plan(day - 1, theme, [], attractions, meals)
    else:
        day_plan = obj

    # LLM 常少写活动/漏餐 → 用代码从候选池补齐（不指望模型自觉）
    day_plan = ensure_day_completeness(day_plan, day, attractions, ctx)
    day_plan = coerce_day(day_plan, day)
    from ..services.xhs_research import attach
    attach({"itinerary":[day_plan]},ctx)
    await ctx_mod.emit({"type": "day", "day": day, "data": day_plan})
    await ctx_mod.emit({"type": "phase", "agent": "composer", "status": "done",
                        "detail": f"Day {day} 已生成（{len(day_plan.get('activities', []))} 个活动）"})
    return day_plan


def _sum_budget(itinerary: List[Dict[str, Any]], days: int) -> Dict[str, Any]:
    """**代码**汇总总预算——不让 LLM 算总账，保证各天口径一致、加总正确。"""
    tickets = 0.0
    food = 0.0
    for day in itinerary:
        for act in _ensure_list(day.get("activities")):
            tickets += float(act.get("ticket_price") or 0)
        for meal in _ensure_list(day.get("meals")):
            food += float(meal.get("estimated_cost") or 0)
    transport = float(max(days * 10, 0))
    return {
        "transport": int(transport),
        "tickets": int(tickets),
        "food": int(food),
        "total": int(tickets + food + transport),
        "currency": "EUR",
    }


async def compose(ctx: PlanningContext) -> Dict[str, Any]:
    """把候选池编成完整行程 dict（结构对齐 TravelPlanData）。按天并发。"""
    assigned = assign_days(ctx)
    ctx.assigned = assigned
    total_assigned = sum(len(v) for v in assigned.values())
    await ctx_mod.emit({"type": "phase", "agent": "composer", "status": "running",
                        "detail": f"按天并发编排（{ctx.days} 天 / {total_assigned} 个去重后景点）"})

    sem = asyncio.Semaphore(DAY_CONCURRENCY)
    day_plans = await asyncio.gather(*[
        _compose_one_day(ctx, day, assigned.get(day, []), sem)
        for day in range(1, ctx.days + 1)
    ])
    itinerary = [d for d in day_plans if isinstance(d, dict)]
    itinerary.sort(key=lambda d: int(d.get("day") or 0))

    ins = ctx.insight or {}
    tips = [str(x) for x in _ensure_list(ins.get("highlights"))][:5]
    warnings = [str(x) for x in _ensure_list(ins.get("avoid"))][:4]

    return {
        "location": ctx.location,
        "days": ctx.days,
        "attractions": _dedupe_by_name(ctx.all_attractions()),
        "itinerary": itinerary,
        "total_budget": _sum_budget(itinerary, ctx.days),
        "tips": tips,
        "warnings": warnings,
    }


async def recompose_day(ctx: PlanningContext, day: int, feedback: str, avoid: Any = (), sem: Any = None) -> Dict[str, Any]:
    """带着审核意见把某一天重排一次。

    avoid：要避开的地点名（其它天已用过的），从这一天的候选里剔除（剔空了就保持原候选，不让这一天没得选）。
    模型输出无效而落入兜底时返回 {}（调用方保留原版，不用兜底顶替一份已经通过的行程）。"""
    ctx.review_feedback[day] = feedback
    bad = {str(n).strip().lower() for n in (avoid or ()) if str(n).strip()}
    atts = list(ctx.assigned.get(day, []))
    kept = [a for a in atts if str(a.get("name") or "").strip().lower() not in bad]
    saved_meals = ctx.meals_by_day.get(day)
    if saved_meals is not None:
        fm = [m for m in saved_meals if str(m.get("name") or "").strip().lower() not in bad]
        ctx.meals_by_day[day] = fm if len(fm) >= 3 else saved_meals
    was_fallback = day in ctx.fallback_days
    try:
        res = await _compose_one_day(ctx, day, kept if len(kept) >= 3 else atts, sem or asyncio.Semaphore(1))
        if day in ctx.fallback_days and not was_fallback:
            ctx.fallback_days.discard(day)
            return {}
        return res
    finally:
        ctx.review_feedback.pop(day, None)
        if saved_meals is not None:
            ctx.meals_by_day[day] = saved_meals
