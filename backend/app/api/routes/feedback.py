"""反馈：对整份行程或某个地点点赞 / 点踩（附原因标签）；站长可看汇总，并和行程的客观质量分对照。"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from ...services.feedback_store import TAGS, get_feedback_store
from ...services.guest_guard import client_ip, get_quota, is_owner, limits as guest_limits, require_owner
from ...services.identity import set_cookie, user_key
from ...services.travel_plan_store import get_travel_plan_store
from ...services.trip_quality import score_trip

router = APIRouter(prefix="/feedback", tags=["Feedback"])


class FeedbackIn(BaseModel):
    result_id: str = Field(..., max_length=64)
    scope: Literal["trip", "place"] = "trip"
    day: int = Field(default=0, ge=0, le=60)
    place: str = Field(default="", max_length=120)
    rating: Literal[-1, 0, 1]
    tags: List[str] = Field(default_factory=list, max_length=10)
    note: str = Field(default="", max_length=500)


@router.post("", summary="提交 / 取消反馈（rating: 1 满意，-1 不满意，0 取消）")
async def submit_feedback(body: FeedbackIn, request: Request, response: Response):
    if body.scope == "place" and not body.place.strip():
        raise HTTPException(status_code=422, detail="地点反馈需要地点名")
    if not get_travel_plan_store().get(body.result_id):
        raise HTTPException(status_code=404, detail="行程不存在")
    if not is_owner(request):
        get_quota().consume("feedback", client_ip(request), guest_limits()["feedback"])
    uk, new_uid = user_key(request)
    set_cookie(response, request, new_uid)
    place = body.place if body.scope == "place" else ""
    rec = get_feedback_store().set(uk, body.result_id, body.scope, body.day if body.scope == "place" else 0, place, body.rating, body.tags, body.note)
    return {"success": True, "item": rec}


@router.get("/mine", summary="我对某份行程的反馈")
async def my_feedback(request: Request, response: Response, result_id: str = Query(..., max_length=64)):
    uk, new_uid = user_key(request)
    set_cookie(response, request, new_uid)
    response.headers["Cache-Control"] = "no-store"
    return {"items": get_feedback_store().mine(uk, result_id), "tags": list(TAGS)}


@router.get("/summary", summary="反馈汇总（仅站长）：满意度、原因标签、差评对应行程的客观问题")
async def feedback_summary(request: Request, limit: int = Query(default=20, ge=1, le=100)):
    require_owner(request)
    rows = get_feedback_store().all_rows()
    store = get_travel_plan_store()
    quality: Dict[str, Dict[str, Any]] = {}

    def q(rid: str) -> Dict[str, Any]:
        if rid not in quality:
            rec = store.get(rid)
            if not rec:
                quality[rid] = {"exists": False}
            else:
                p = rec.get("payload") or {}
                s = score_trip(p)
                quality[rid] = {"exists": True, "location": p.get("location", ""), "score": s["score"], "issues": [i["text"] for i in s["issues"][:5]]}
        return quality[rid]

    ups = [r for r in rows if r["rating"] > 0]
    downs = [r for r in rows if r["rating"] < 0]
    tags: Dict[str, int] = {}
    for r in downs:
        for t in r["tags"]:
            tags[t] = tags.get(t, 0) + 1
    scores_up = [q(r["result_id"])["score"] for r in ups if q(r["result_id"]).get("exists")]
    scores_down = [q(r["result_id"])["score"] for r in downs if q(r["result_id"]).get("exists")]
    avg = lambda xs: round(sum(xs) / len(xs), 1) if xs else None   # noqa: E731
    return {
        "total": len(rows), "up": len(ups), "down": len(downs),
        "by_scope": {s: sum(1 for r in rows if r["scope"] == s) for s in ("trip", "place")},
        "down_tags": dict(sorted(tags.items(), key=lambda x: -x[1])),
        "avg_quality_up": avg(scores_up), "avg_quality_down": avg(scores_down),
        "recent_down": [{**r, "trip": q(r["result_id"])} for r in downs[:limit]],
    }

