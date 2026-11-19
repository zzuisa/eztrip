"""对“已经成型的行程”做一次最终审核（不重排）。

用在三个地方，规则只有一条：**行程指纹与审核指纹不一致，就必须重审**——
  1. 生成流程的出口守卫：多城市合并、旧流水线等没有走 agent 闭环的结果；
  2. 用户编辑行程（保存 / 恢复 / 平移时间）之后：先重建交通（settle fit=False，不替用户改行程），再审核；
  3. 读取已保存行程时发现审核过期（旧行程、或编辑后审核还没跑完）。

用户手动改过的行程不会被自动改写；审核意见留在 review 记录里（issues），不会变成一堆“提醒”。
"""

from __future__ import annotations

import asyncio
import copy
import logging
from typing import Any, Dict, List, Optional

from ..services import finalize, long_review
from ..services.llm_service import get_llm_router
from ..services.model_config import get_model
from ..services.travel_plan_store import get_travel_plan_store
from . import reviewer

log = logging.getLogger(__name__)

_IN_FLIGHT: set = set()


async def review_payload(payload: Dict[str, Any], meta: Dict[str, Any], *, source: str = "final") -> Dict[str, Any]:
    """审核 payload 当前这一份行程；返回带 fingerprint / source 的 review（status 可能是 skipped/failed）。"""
    itin = [d for d in (payload.get("itinerary") or []) if isinstance(d, dict)]
    known = [c["message"] for c in finalize.hard_checks(payload, meta)]
    review = await reviewer.review_itinerary(
        router=get_llm_router(), model=get_model("review"), location=str(payload.get("location") or ""),
        days=len(itin) or int(payload.get("days") or 1), preferences=str(payload.get("request_preferences") or ""),
        transport=str(meta.get("transportation") or ""), origin=str(meta.get("origin") or ""),
        dates=str(meta.get("start_date") or ""), itinerary=itin, known=known, weather=payload.get("weather"), meta=meta)
    passes=1 if review.get('status')=='ok' else 0
    if len(itin)>=8:
        second=await reviewer.review_itinerary(
            router=get_llm_router(),model=get_model('review'),location=str(payload.get('location') or ''),
            days=len(itin),preferences=str(payload.get('request_preferences') or ''),transport=str(meta.get('transportation') or ''),
            origin=str(meta.get('origin') or ''),dates=str(meta.get('start_date') or ''),itinerary=itin,known=known,
            weather=payload.get('weather'),meta=meta,round_no=2,
            prior=['专项独立复核换城、每晚住宿与首末日衔接，不能只沿用第一轮结论'])
        passes += int(second.get('status')=='ok')
        review=long_review.merge(review,second)
        long_review.include_hard_checks(review,finalize.hard_checks(payload,meta))
        long_review.apply(review,payload,meta,passes)
    from ..services.experiences import diversity_issues
    variety=diversity_issues(itin,str(payload.get('request_preferences') or ''))
    review['issues']=[*(review.get('issues') or []),*variety]
    if variety:
        review['verdict']='revise'
        if (review.get('quality_gate') or {}).get('state')=='passed':review['quality_gate'].update(state='needs_attention',summary='体验结构与偏好仍需调整，当前保留草案')
    review["fingerprint"] = finalize.fingerprint(payload)
    review["source"] = source
    return review


def apply_review(payload: Dict[str, Any], review: Dict[str, Any]) -> None:
    """把审核结果写进 payload：review 记录 + 重算“程序检查类”提醒（不把审核意见当提醒）。"""
    payload["review"] = reviewer.public_view(review)
    if review.get('quality_gate'):payload['planning_status']=review['quality_gate']['state']
    payload["fingerprint"] = review.get("fingerprint") or finalize.fingerprint(payload)
    meta = payload.get("trip_meta") or {}
    new = [c["message"] for c in finalize.hard_checks(payload, meta)]
    old = set(str(x) for x in (payload.get("check_warnings") or []))
    payload["warnings"] = list(dict.fromkeys([*[w for w in (payload.get("warnings") or []) if str(w) not in old], *new]))
    payload["check_warnings"] = new
    tips = [t for t in (payload.get("tips") or []) if not str(t).startswith("出行提示：")]
    payload["tips"] = list(dict.fromkeys([*tips, *reviewer.to_tips(review)]))


def needs_review(payload: Dict[str, Any]) -> bool:
    itin = [d for d in (payload.get("itinerary") or []) if isinstance(d, dict)]
    legacy_long=len(itin)>=8 and ((payload.get('review') or {}).get('quality_gate') or {}).get('policy')!=long_review.VERSION
    return bool(itin) and reviewer.should_review(len(itin)) and (legacy_long or not finalize.is_reviewed(payload))


async def review_stored(result_id: str, source: str = "edit") -> Optional[Dict[str, Any]]:
    """已保存行程：重建交通 → 审核 → 回写（保存时 rev 变了说明又有新编辑，丢弃这次结果，由新的那次负责）。"""
    if result_id in _IN_FLIGHT:
        return None
    _IN_FLIGHT.add(result_id)
    try:
        store = get_travel_plan_store()
        rec = store.get(result_id)
        if not rec:
            return None
        rev = int(rec.get("rev") or 0)
        payload = copy.deepcopy(rec.get("payload") or {})
        meta = dict(payload.get("trip_meta") or {})
        if not payload.get("itinerary"):
            return None
        finalize.settle(payload, meta, fit=False)          # 只重建交通，不替用户改行程
        review = await review_payload(payload, meta, source=source)

        def mut(r: Dict[str, Any]) -> Optional[bool]:
            if int(r.get("rev") or 0) != rev:
                return False
            p = r.setdefault("payload", {})
            if finalize.fingerprint(p) != review.get("fingerprint"):
                return False                                    # 期间行程又变了：这次审核已过期
            apply_review(p, review)
            return True

        store.update_record(result_id, mut)
        return review
    except Exception as e:                                       # noqa: BLE001
        log.warning("行程重审失败 %s: %s", result_id, e)
        return None
    finally:
        _IN_FLIGHT.discard(result_id)

