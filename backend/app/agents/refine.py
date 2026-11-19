"""审核—修订闭环：把审核员指出的问题交回编排器修订，再复审，直到行程“干净”再交付。

铁律：**审核永远发生在最终数据之后**。
    每一轮：润色（含营业时间）→ settle（到达/取还车/返程/可游览窗口/放不下的活动，services/finalize.py）→ 审核；
    重排之后同样要重新润色 + settle 才复审；交付的是“被审核过的那一份”，之后不再有任何改动行程的步骤
    （预算只读行程，图片/天气只加字段；fingerprint 把关，见 finalize.is_reviewed）。

流程（每一步都向前端推 refine / phase 事件，生成等待页实时展示）：
    [润色 → settle → 审核] → [有中/高问题且评分未达标] 带意见 + 当天硬约束重排相关天 → [润色 → settle → 复审] … （最多 max_rounds 次重排）

原则：
- 用户看到的是修订后的行程；审核意见不再原样甩给用户（审核记录保留在 review 里）。
- 每一轮都复审；若重排后评分反而更低，回到上一版（只交付审核过的版本）。
- 总时长有上限（total_timeout_seconds），到点就以当前最好的一版交付，不无限等待。
- 审核服务不可用不会拖垮规划：第一轮就失败 → 照常交付 settle 后的行程（review.status=skipped/failed）。
"""

from __future__ import annotations

import asyncio
import copy
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from ..agent_config import agent as agent_cfg
from ..services import finalize, voice
from ..services.day_geo import filter_attractions, sanitize_itinerary
from ..services.itinerary_utils import _ensure_list
from ..services.llm_service import get_llm_router
from ..services.meal_utils import _enforce_meal_quality_on_itinerary
from ..services.model_config import get_model
from . import context as ctx_mod
from . import polish, reviewer
from .composer import _sum_budget, recompose_day

log = logging.getLogger(__name__)

_INFO_MARKS = ("已改到", "已从当天移除")      # 营业时间校验“已经处理掉”的说明：只是告知，不是待办问题


def _pub(issues: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [{k: i[k] for k in ("day", "severity", "type", "message")} for i in issues]


async def _emit(stage: str, **kw: Any) -> None:
    await ctx_mod.emit({"type": "refine", "stage": stage, **kw})


def prepare(ctx, itinerary: List[Dict[str, Any]], plan: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """润色 + 最终化（就地修改 itinerary）。返回 {notes, checks, hours_unresolved, fingerprint}。

    这一步之后的行程就是“用户将拿到的行程”，审核必须基于它。"""
    itinerary[:] = voice.scrub_value(itinerary)                # 话术净化放在审核之前：审核看到的就是用户最终看到的文字
    polish.apply(itinerary, ctx)                               # 去重餐厅 / 停留底线 / 营业时间 / 用餐时间
    first_pass = [str(x) for x in (getattr(ctx, "hours_issues", None) or [])]
    view = {**(plan or {}), "itinerary": itinerary, "location": ctx.location, "days": ctx.days}
    info: Dict[str, Any] = {"notes": [], "checks": [], "fingerprint": ""}
    if ctx.trip_meta is not None:
        info = finalize.settle(view, ctx.trip_meta)
    else:
        info["fingerprint"] = finalize.fingerprint(view)
    # settle 之后再核一次营业时间（只读：在副本上算，剩下的才是需要告诉用户的）
    try:
        from . import feasibility
        feasibility.apply(copy.deepcopy(itinerary), ctx)
        unresolved = [str(x) for x in (ctx.hours_issues or [])]
    except Exception as e:                                       # noqa: BLE001
        log.warning("营业时间终检失败（跳过）: %s", e)
        unresolved = [x for x in first_pass if not any(m in x for m in _INFO_MARKS)]
    ctx.hours_issues = unresolved
    info["hours_unresolved"] = unresolved
    info["notes"] = [*info.get("notes", []), *[x for x in first_pass if any(m in x for m in _INFO_MARKS)]]
    return info


async def _revise(ctx, cur_it: List[Dict[str, Any]], picks: Dict[int, Dict[str, Any]], service, location: str
                  ) -> Tuple[List[Dict[str, Any]], List[str], List[int]]:
    """重排 picks 里的天；返回 (新行程, 程序警告, 实际改动的天)。润色与最终化统一放在下一轮开头做。"""
    sem = asyncio.Semaphore(3)
    days_ = list(picks)
    for d in days_:      # 告诉编排器这一天还有哪些没用到的候选，方便它补空档 / 替换重复项
        used = {str(a.get("name") or "").strip().lower() for x in cur_it if int(x.get("day") or 0) == d for a in _ensure_list(x.get("activities")) if isinstance(a, dict)}
        spare = [str(a.get("name")) for a in ctx.assigned.get(d, []) if str(a.get("name") or "").strip().lower() not in used][:6]
        if spare:
            picks[d]["feedback"] = (picks[d]["feedback"] + "；这一天还没用到的候选景点：" + "、".join(spare) + "（可用来填补空档或替换重复项）")[:520]
        limits = finalize.day_constraints({"itinerary": cur_it}, ctx.trip_meta or {}, d) if ctx.trip_meta else ""
        if limits:       # 与 settle 同一套硬约束，重排出来的结果不会再被删改
            picks[d]["feedback"] = (picks[d]["feedback"] + "；硬约束：" + limits)[:700]
    results = await asyncio.gather(*[recompose_day(ctx, d, picks[d]["feedback"], picks[d]["avoid"], sem) for d in days_],
                                   return_exceptions=True)
    by_day = {int(x.get("day") or 0): x for x in cur_it}
    changed: List[int] = []
    for d, res in zip(days_, results):
        if isinstance(res, dict) and res.get("activities"):
            by_day[d] = res
            changed.append(d)
        else:
            log.warning("第 %s 天按审核意见重排失败，保留原版: %s", d, res)
    if not changed:
        return cur_it, [], []
    try:
        merged, _m = await asyncio.to_thread(
            _enforce_meal_quality_on_itinerary, service=service, location=location,
            itinerary=[by_day[d] for d in changed], daily_meal_sources=ctx.meal_sources)
        by_day.update({int(x.get("day") or 0): x for x in merged})
    except Exception as e:                           # noqa: BLE001
        log.warning("重排后餐饮校验失败（跳过）: %s", e)
    itin, geo, _stats = sanitize_itinerary([by_day[k] for k in sorted(by_day)])
    for d in sorted(ctx.fallback_days):
        geo.append(f"Day {d}：可用的候选地点不足，内容是保守安排，建议用“调整这一站”补充或重新规划")
    return itin, geo, sorted(changed)


def settle_only(ctx, plan: Dict[str, Any], itinerary: List[Dict[str, Any]]) -> Dict[str, Any]:
    """不需要审核的行程（单日 / 审核关闭）：同样要最终化，保证交付的时间线走得通。"""
    info = prepare(ctx, itinerary, plan)
    plan["itinerary"] = itinerary
    plan["settle_notes"] = info["notes"]
    plan["hard_checks"] = [c["message"] for c in info["checks"]]
    plan["fingerprint"] = info["fingerprint"]
    return info


async def refine_plan(ctx, plan: Dict[str, Any], itinerary: List[Dict[str, Any]], geo_warnings: List[str], service,
                      location: str, days: int, preferences: str, origin: str):
    """返回 (最终行程, 程序警告, 审核结果)。plan 里的 itinerary / attractions / total_budget / settle_notes / hard_checks 同步更新。"""
    from ..services import long_review
    cfg = long_review.policy(days, reviewer.settings())
    max_rounds = max(0, int(cfg.get("max_rounds", 2)))
    target = int(cfg.get("target_score", 85))
    max_rev = int(cfg.get("max_revisions", 6))
    deadline = time.monotonic() + float(cfg.get("total_timeout_seconds", 200))
    model = get_model("review")
    ctx.revise_model = str(agent_cfg("critic").get("revise_model") or model)
    total = max_rounds + 1

    cur_it, cur_geo = itinerary, geo_warnings
    best: Optional[Dict[str, Any]] = None
    rounds: List[Dict[str, Any]] = []
    revised_all: set = set()
    prior: List[str] = []
    first_score: Optional[int] = None
    await ctx_mod.emit({"type": "phase", "agent": "critic", "status": "running", "detail": "独立审核行程的路线、节奏与用餐"})

    for n in range(1, total + 1):
        # ① 先把行程排定成最终形态（到达/取还车/返程/窗口/营业时间），② 再审核它
        info = prepare(ctx, cur_it, plan)
        await _emit("review_start", round=n, total=total)
        known = [*cur_geo, *[c["message"] for c in info["checks"]], *info["hours_unresolved"]]
        review = await reviewer.review_itinerary(
            router=get_llm_router(), model=model, location=location, days=days, preferences=preferences,
            transport=ctx.transportation, origin=origin, dates=ctx.start_date or "", itinerary=cur_it,
            known=known, round_no=n, prior=prior, weather=ctx.weather, meta=ctx.trip_meta)
        review["fingerprint"] = info["fingerprint"]
        if review.get("status") != "ok":
            if best is None:
                await _emit("skipped", round=n, total=total)
                await ctx_mod.emit({"type": "phase", "agent": "critic", "status": "done", "detail": "审核暂不可用，已跳过"})
                plan["itinerary"] = itinerary = cur_it
                plan["settle_notes"] = info["notes"]
                plan["hard_checks"] = [c["message"] for c in info["checks"]]
                return itinerary, cur_geo, review
            break
        from ..services.experiences import diversity_issues
        variety=diversity_issues(cur_it,preferences)
        review['issues']=[*(review.get('issues') or []),*variety]
        if variety:review['verdict']='revise'
        if days>=8:long_review.include_hard_checks(review,info['checks'])
        score = int(review["score"])
        first_score = score if first_score is None else first_score
        rounds.append({"round": n, "score": score, "issues": len(review["issues"]), "revised": []})
        await _emit("review_done", round=n, total=total, score=score, summary=review.get("summary", ""), issues=_pub(review["issues"]))
        highs = sum(1 for i in review["issues"] if i["severity"] == "high")
        if best is not None and (highs > best["highs"] or (highs == best["highs"] and score + 2 < best["score"])):
            await _emit("revert", round=n, score=score, kept=best["score"])
            break                                       # 重排后更差（硬伤更多或评分更低）：保留上一版
        stalled = best is not None and score <= best["score"] and highs >= best["highs"]
        if not (stalled and score < best["score"]):
            best = {"score": score, "highs": highs, "it": copy.deepcopy(cur_it), "geo": cur_geo, "review": review,
                    "revised": set(revised_all), "info": info}

        picks = reviewer.plan_feedback(review, cur_it, max_rev)
        clean = score >= target and not variety and not any(i["severity"] == "high" for i in review["issues"])
        if clean and n < cfg['min_passes']:
            prior = ['继续独立检查跨城衔接、每晚住宿、首末日交通及餐饮时间，不能只因评分达标结束']
            continue
        if not picks or clean or (stalled and (days<8 or n>=3)) or n == total or deadline - time.monotonic() < 45:
            break
        prior = [i["message"] for i in reviewer.actionable(review)][:6]
        await _emit("revise_start", round=n, total=total, days=sorted(picks),
                    notes=[{"day": d, "text": (p["issues"][0]["message"] if p["issues"] else "")} for d, p in sorted(picks.items())])
        await ctx_mod.emit({"type": "phase", "agent": "critic", "status": "running",
                            "detail": "第 %d 轮：按审核意见重新编排 %s" % (n, "、".join("Day %d" % d for d in sorted(picks)))})
        work = copy.deepcopy(cur_it)                     # 重排在副本上做：失败/变差时 best 不受影响
        new_it, new_geo, changed = await _revise(ctx, work, picks, service, location)
        await _emit("revise_done", round=n, total=total, days=changed)
        if not changed:
            break
        rounds[-1]["revised"] = changed
        revised_all.update(changed)
        cur_it, cur_geo = new_it, new_geo

    assert best is not None
    review = best["review"]
    long_review.apply(review, {'itinerary':best['it']},ctx.trip_meta or {},passes=len(rounds))
    review["revised_days"] = sorted(best["revised"])
    review["rounds"] = rounds
    review["initial_score"] = first_score if first_score is not None else best["score"]
    itin = best["it"]                                    # 已 settle、已审核的那一份：从这里起不再改动行程
    ctx.hours_issues = list(best["info"].get("hours_unresolved") or [])
    plan["itinerary"] = itin
    plan["attractions"] = filter_attractions(_ensure_list(plan.get("attractions")), itin)
    plan["total_budget"] = _sum_budget(itin, days)
    plan["settle_notes"] = best["info"]["notes"]
    plan["hard_checks"] = [c["message"] for c in best["info"]["checks"]]
    await _emit("final", score=best["score"], initial_score=review["initial_score"], rounds=len(rounds),
                revised_days=review["revised_days"], remaining=len([i for i in review["issues"] if i["severity"] != "low"]))
    await ctx_mod.emit({"type": "phase", "agent": "critic", "status": "done",
                        "detail": "最终检查完成"})
    return itin, best["geo"], review

