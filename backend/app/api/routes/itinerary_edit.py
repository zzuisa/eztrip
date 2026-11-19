"""行程编辑：保存修改（带历史/版本）、地点搜索、AI 修改提案、复制为自己的行程。

访问模型（结果页链接任何人可读，所以写操作必须鉴权）：
- 站长（Basic 凭据）：可编辑任何行程。
- 游客：只能编辑“自己生成/自己复制”的行程——记录里存有生成者的匿名 ez_uid（Cookie），与当前 Cookie 一致才可写。
  看别人分享的行程时可以“复制为我的行程”（fork）后再编辑。
- editor 存在记录顶层，不在 payload 里，永远不会随 GET 返回。
AI 修改只产出“提案”（不落库）；用户在前端预览 diff 后再通过 PUT 保存，因此是否生效由用户决定。
"""

from __future__ import annotations

import asyncio
import copy
import math
import os
import time
from typing import Any, Dict, List, Literal, Optional

import httpx
from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from ...config import get_settings
from ...services import itinerary_edit as ie
from ...services.guest_guard import client_ip, get_quota, is_owner, limits as guest_limits
from ...services.identity import can_edit, set_cookie, user_key
from ...services.llm_service import get_llm_router
from ...services.model_config import get_model
from ...services.travel_plan_store import get_travel_plan_store

router = APIRouter(prefix="/travel-plan", tags=["ItineraryEdit"])

HISTORY_KEEP = 8
_ai_sem = asyncio.Semaphore(2)


def edit_model() -> str:
    return get_model("itinerary_edit")


# ---------------------------------------------------------------- 权限


def _record(result_id: str) -> Dict[str, Any]:
    rec = get_travel_plan_store().get(result_id)
    if not rec:
        raise HTTPException(status_code=404, detail="记录不存在")
    return rec


def _require_editor(request: Request, rec: Dict[str, Any]) -> None:
    if not can_edit(request, rec):
        raise HTTPException(status_code=403, detail={"code": "not_editor", "message": "这份行程不是你创建的，可以先「复制为我的行程」再编辑"})


def _consume(kind: str, request: Request) -> bool:
    """游客占额度；返回是否占用了（用于失败时退还）。"""
    if is_owner(request):
        return False
    get_quota().consume(kind, client_ip(request), guest_limits()[kind])
    return True


# ---------------------------------------------------------------- 地图检索


def _centroid(itinerary: List[Dict[str, Any]], day_idx: Optional[int] = None) -> Optional[tuple]:
    pts = []
    for di, d in enumerate(itinerary):
        if day_idx is not None and di != day_idx:
            continue
        for it in list(d.get("activities") or []) + list(d.get("meals") or []):
            if isinstance(it, dict) and it.get("latitude") is not None and it.get("longitude") is not None:
                pts.append((float(it["latitude"]), float(it["longitude"])))
    if not pts and day_idx is not None:
        return _centroid(itinerary, None)
    if not pts:
        return None
    return sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)


def _km(a: tuple, b: tuple) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


def _search_sync(query: str, anchor: Optional[tuple], limit: int = 5, max_km: float = 40.0) -> List[Dict[str, Any]]:
    from ...services.google_places_service import get_google_places_service

    try:
        raw = get_google_places_service().search_places(query, limit=limit)
    except Exception as e:  # noqa: BLE001
        print(f"[itinerary-edit] search failed {type(e).__name__}: {e}")
        return []
    out = []
    for p in raw:
        if p.get("lat") is None or p.get("lng") is None:
            continue
        item = {
            "name": p.get("name") or "", "address": p.get("formatted_address") or "", "latitude": float(p["lat"]), "longitude": float(p["lng"]),
            "rating": p.get("rating"), "summary": p.get("editorial_summary") or "", "ticket_price": p.get("ticket_price") or 0, "place_id": p.get("place_id") or "",
        }
        if anchor:
            item["distance_km"] = round(_km(anchor, (item["latitude"], item["longitude"])), 1)
            if item["distance_km"] > max_km:
                continue
        out.append(item)
    if anchor:
        out.sort(key=lambda x: x.get("distance_km", 0))
    return out


def _same_place(want: str, got: str) -> bool:
    a, b = want.lower().strip(), got.lower().strip()
    return bool(a) and bool(b) and (a in b or b in a)


async def _locate(name: str, query: str, anchor: Optional[tuple]) -> Optional[Dict[str, Any]]:
    res = await asyncio.to_thread(_search_sync, query, anchor, 5)
    if not res:
        return None
    for r in res:  # 优先名称吻合的；否则取最近的（并采用其真实名称）
        if _same_place(name, r["name"]):
            return {**r, "name": name}
    return res[0]


@router.get("/place-search", summary="按名称搜索地点（供添加行程节点）")
async def place_search(
    request: Request,
    q: str = Query(..., min_length=1, max_length=80),
    city: str = Query("", max_length=60),
    lat: Optional[float] = Query(None, ge=-90, le=90),
    lng: Optional[float] = Query(None, ge=-180, le=180),
):
    _consume("psearch", request)
    anchor = (lat, lng) if lat is not None and lng is not None else None
    items = await asyncio.to_thread(_search_sync, ("%s %s" % (q, city)).strip(), anchor, 8, 80.0)
    return {"success": True, "items": items[:8]}


# ---------------------------------------------------------------- 保存


class DaySubmit(BaseModel):
    day: int = 0
    activities: List[Dict[str, Any]] = Field(default_factory=list)
    meals: List[Dict[str, Any]] = Field(default_factory=list)


class SaveReq(BaseModel):
    rev: int = 0
    days: List[DaySubmit]


async def _geocode_missing(itinerary: List[Dict[str, Any]], city: str, cap: int = 8) -> List[Dict[str, Any]]:
    missing = ie.needs_geocode(itinerary)[:cap]
    if not missing:
        return []

    async def one(pos):
        di, is_meal, idx = pos
        it = (itinerary[di].get("meals") if is_meal else itinerary[di].get("activities"))[idx]
        q = ("%s %s %s" % (it.get("name", ""), it.get("address", ""), city)).strip()
        return pos, await _locate(str(it.get("name", "")), q, _centroid(itinerary, di))

    filled = []
    try:
        results = await asyncio.wait_for(asyncio.gather(*[one(p) for p in missing], return_exceptions=True), timeout=15)
    except asyncio.TimeoutError:
        results = []
    for r in results:
        if isinstance(r, Exception) or not r[1]:
            continue
        (di, is_meal, idx), loc = r
        it = (itinerary[di].get("meals") if is_meal else itinerary[di].get("activities"))[idx]
        it["latitude"], it["longitude"] = loc["latitude"], loc["longitude"]
        if not it.get("address"):
            it["address"] = loc.get("address") or ""
        if loc.get("rating") is not None and "rating" not in it:
            it["rating"] = loc["rating"]
        filled.append({"day": di + 1, "is_meal": is_meal, "name": it["name"], "latitude": it["latitude"], "longitude": it["longitude"], "address": it.get("address", ""), "rating": it.get("rating")})
    return filled


def _rebuild_transits(payload: Dict[str, Any]) -> None:
    """行程被改写/恢复后，每天开头/结尾的交通按新顺序重新计算（出发地、住宿、跨城都已在 trip_meta 里）。"""
    try:
        from ...services import transit_plan as transit_svc

        transit_svc.build(payload, dict(payload.get("trip_meta") or {}))
        from ...services import finalize
        old_checks = set(str(x) for x in (payload.get("check_warnings") or []))
        checks = [c["message"] for c in finalize.hard_checks(payload, dict(payload.get("trip_meta") or {}))]
        payload["warnings"] = list(dict.fromkeys([*[w for w in (payload.get("warnings") or []) if str(w) not in old_checks], *checks]))
        payload["check_warnings"] = checks
    except Exception as e:  # noqa: BLE001
        print(f"[transit] rebuild failed {type(e).__name__}: {e}")


def _schedule_review(result_id: str) -> None:
    """用户改动行程之后：重建交通 → 重新审核（后台；不改用户的行程，意见记在 review 里）。"""
    try:
        from ...agents import final_review
        from .travel_plan import _spawn

        _spawn(final_review.review_stored(result_id, source="edit"))
    except Exception as e:  # noqa: BLE001
        print(f"[review] schedule failed {type(e).__name__}: {e}")


def _write_itinerary(result_id: str, expect_rev: int, new_itinerary: List[Dict[str, Any]]) -> Dict[str, Any]:
    state: Dict[str, Any] = {}

    def mut(rec: Dict[str, Any]) -> Optional[bool]:
        if int(rec.get("rev") or 0) != expect_rev:
            state["conflict"] = int(rec.get("rev") or 0)
            return False
        payload = rec.setdefault("payload", {})
        old = copy.deepcopy(payload.get("itinerary") or [])
        rec.setdefault("original", old)
        hist = rec.setdefault("history", [])
        hist.append({"rev": expect_rev, "at": int(time.time()), "itinerary": old})
        del hist[:-HISTORY_KEEP]
        payload["itinerary"] = new_itinerary
        from ...services.route_sync import rebuild
        rebuild(payload, old)
        _rebuild_transits(payload)
        if payload.get("story"):
            payload["story_stale"] = True
        rec["rev"] = expect_rev + 1
        state["rev"] = rec["rev"]
        return True

    ok = get_travel_plan_store().update_record(result_id, mut)
    if not ok and "conflict" in state:
        raise HTTPException(status_code=409, detail={"code": "rev_conflict", "message": "行程已在别处修改，请刷新后再编辑", "rev": state["conflict"]})
    if not ok:
        raise HTTPException(status_code=404, detail="记录不存在")
    return state


@router.put("/results/{result_id}/itinerary", summary="保存对行程的修改（拖拽/增删改后的整体结果）")
async def save_itinerary(result_id: str, req: SaveReq, request: Request):
    rec = _record(result_id)
    _require_editor(request, rec)
    _consume("edit", request)
    payload = rec.get("payload") or {}
    itinerary = payload.get("itinerary") or []
    try:
        new_it = ie.apply_days(itinerary, [d.model_dump() for d in req.days])
    except ie.EditError as e:
        raise HTTPException(status_code=422, detail=str(e))
    filled = await _geocode_missing(new_it, str(payload.get("location") or ""))
    state = _write_itinerary(result_id, req.rev, new_it)
    from .travel_plan import _enrich_result_images, _spawn, _payload_missing_images

    if _payload_missing_images({"itinerary": new_it}):
        _spawn(_enrich_result_images(result_id))
    saved = get_travel_plan_store().get(result_id) or {}
    budget_out = None
    transits_out = None
    try:  # 编辑后按新行程快速重算预算（不联网，沿用已查到的票价与住宿单价）
        from ...services import budget as budget_svc

        from ...services import transit_plan as transit_svc

        sp_ = saved.get("payload") or {}
        meta_ = dict(sp_.get("trip_meta") or {})
        if (sp_.get("total_budget") or {}).get("detail"):
            budget_out = await budget_svc.build_budget(sp_, meta_, reuse=sp_["total_budget"])
        else:
            transit_svc.build(sp_, meta_)
        transits_out = transit_svc.snapshot(sp_.get("itinerary") or [])

        def _persist(record, _b=budget_out, _it=sp_.get("itinerary") or []):
            if int(record.get("rev") or 0) != state["rev"]:
                return False
            p = record.setdefault("payload", {})
            if _b:
                p["total_budget"] = _b
            transit_svc.copy_transits(_it, p.get("itinerary") or [])
            return True
        get_travel_plan_store().update_record(result_id, _persist)
    except Exception as e:  # noqa: BLE001
        print(f"[budget] quick recompute failed {type(e).__name__}: {e}")
    _schedule_review(result_id)
    fresh = get_travel_plan_store().get(result_id) or {}
    return {"success": True, "rev": int(fresh.get("rev") or state["rev"]), "updated_at": fresh.get("updated_at"), "filled": filled, "total_budget": budget_out, "transits": transits_out, "review_stale": True, "data": {**(fresh.get("payload") or {}), "result_id": result_id, "review_stale": True}}


class RestoreReq(BaseModel):
    to: Literal["original", "previous"] = "original"


@router.post("/results/{result_id}/restore", summary="恢复行程：AI 初版 / 上一个已保存版本")
async def restore_itinerary(result_id: str, req: RestoreReq, request: Request):
    rec = _record(result_id)
    _require_editor(request, rec)
    _consume("edit", request)
    state: Dict[str, Any] = {}

    def mut(r: Dict[str, Any]) -> Optional[bool]:
        hist = r.setdefault("history", [])
        if req.to == "original":
            target = r.get("original")
        else:
            target = hist.pop()["itinerary"] if hist else None
        if not target:
            state["none"] = True
            return False
        payload = r.setdefault("payload", {})
        hist.append({"rev": int(r.get("rev") or 0), "at": int(time.time()), "itinerary": copy.deepcopy(payload.get("itinerary") or [])})
        del hist[:-HISTORY_KEEP]
        payload["itinerary"] = copy.deepcopy(target)
        from ...services.route_sync import rebuild
        rebuild(payload)
        _rebuild_transits(payload)
        if payload.get("story"):
            payload["story_stale"] = True
        r["rev"] = int(r.get("rev") or 0) + 1
        return True

    if not get_travel_plan_store().update_record(result_id, mut):
        raise HTTPException(status_code=404, detail="没有可恢复的版本" if state.get("none") else "记录不存在")
    fresh = get_travel_plan_store().get(result_id) or {}
    _schedule_review(result_id)
    return {"success": True, "rev": fresh.get("rev", 0), "data": {**(fresh.get("payload") or {}), "result_id": result_id, "review_stale": True}}


@router.post("/results/{result_id}/fork", summary="复制为我的行程（之后可自由编辑）")
async def fork_result(result_id: str, request: Request, response: Response):
    rec = _record(result_id)
    _consume("fork", request)
    uk, new_uid = user_key(request)
    payload = copy.deepcopy(rec.get("payload") or {})
    for k in ("story", "story_stale"):
        payload.pop(k, None)
    new_id = get_travel_plan_store().save(payload)
    get_travel_plan_store().update_record(new_id, lambda r: r.update({"editor": uk, "forked_from": result_id, "rev": 0}))
    set_cookie(response, request, new_uid)
    return {"success": True, "id": new_id}


# ---------------------------------------------------------------- AI 修改提案


class PlaceRef(BaseModel):
    day: int = Field(ge=1, le=60)
    name: str = Field(min_length=1, max_length=120)


class AiEditReq(BaseModel):
    instruction: str = Field(min_length=1, max_length=400)
    scope: Literal["trip", "day", "place"] = "trip"
    day: Optional[int] = Field(default=None, ge=1, le=60)
    place: Optional[PlaceRef] = None


async def _complete(messages: List[Dict[str, str]]) -> str:
    r = get_llm_router()
    if not r.api_key:
        raise RuntimeError("LLM 未配置")
    body = {"model": edit_model(), "messages": messages, "temperature": 0.4, "max_tokens": int(os.getenv("EZTRIP_EDIT_MAX_TOKENS", "4000")), **r._extra()}
    async with httpx.AsyncClient(timeout=httpx.Timeout(connect=8.0, read=100.0, write=10.0, pool=8.0)) as c:
        resp = await c.post(f"{r.base_url}/chat/completions", headers={"Authorization": f"Bearer {r.api_key}", "Content-Type": "application/json"}, json=body)
    if resp.status_code >= 400:
        raise RuntimeError(f"upstream {resp.status_code}")
    return (((resp.json().get("choices") or [{}])[0]).get("message") or {}).get("content") or ""


@router.post("/{result_id}/ai-edit", summary="AI 修改提案（不落库，预览后由用户确认保存）")
async def ai_edit(result_id: str, req: AiEditReq, request: Request):
    rec = _record(result_id)
    _require_editor(request, rec)
    payload = rec.get("payload") or {}
    itinerary = payload.get("itinerary") or []
    if not itinerary:
        raise HTTPException(status_code=422, detail="行程为空")
    refs = ie.build_refs(itinerary)

    target_ref: Optional[str] = None
    if req.scope == "place":
        if not req.place:
            raise HTTPException(status_code=422, detail="缺少所选地点")
        target_ref = next((k for k, v in refs.items() if v["day"] == req.place.day - 1 and v["item"].get("name") == req.place.name), None)
        if not target_ref:
            raise HTTPException(status_code=404, detail="所选地点已不在行程中")
        focus = [refs[target_ref]["day"]]
    elif req.scope == "day":
        if not req.day or req.day > len(itinerary):
            raise HTTPException(status_code=422, detail="缺少或超出范围的天数")
        focus = [req.day - 1]
    else:
        focus = list(range(len(itinerary)))

    consumed = _consume("aiedit", request)
    try:
        async with _ai_sem:
            messages = ie.build_messages(payload, refs, focus, req.instruction, target_ref)
            proposal = None
            last_err = "输出格式不合格"
            for _attempt in range(2):
                content = await _complete(messages)
                try:
                    proposal = ie.parse_proposal(content, payload, refs, focus, target_ref)
                    break
                except ie.ProposalError as e:
                    last_err = str(e)
            if proposal is None:
                raise RuntimeError(last_err)
            city = str(payload.get("location") or "")

            async def loc(di: int, si: int, slot: Dict[str, Any]):
                return (di, si), await _locate(slot["name"], ("%s %s" % (slot["search"], city)).strip(), _centroid(itinerary, di))

            jobs = [loc(dd["day_idx"], si, s) for dd in proposal["days"] for si, s in enumerate(dd["slots"]) if not s["ref"]]
            located: Dict[Any, Any] = {}
            for r in await asyncio.gather(*jobs, return_exceptions=True):
                if not isinstance(r, Exception) and r[1]:
                    located[r[0]] = r[1]
            result = ie.assemble(payload, refs, proposal, located)
        return {"success": True, "scope": req.scope, "model": edit_model(), "rev": int(rec.get("rev") or 0), **result}
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        if consumed:
            get_quota().refund("aiedit", client_ip(request))
        print(f"[itinerary-edit] ai-edit error {type(e).__name__}: {e}")
        raise HTTPException(status_code=502, detail="这次没有生成可用的修改，请换个说法再试")



class DayRetimeReq(BaseModel):
    day: int = Field(ge=1, le=15)
    start: str = Field(pattern=r'^([01]\d|2[0-3]):[0-5]\d$')
    end: str = Field(pattern=r'^([01]\d|2[0-3]):[0-5]\d$')
    rev: int = Field(ge=0)
    preview: bool = True


@router.post('/results/{result_id}/day-retime')
async def day_retime(result_id: str, req: DayRetimeReq, request: Request):
    from ...services.day_rhythm import retime
    rec = _record(result_id)
    _require_editor(request, rec)
    if int(rec.get('rev') or 0) != req.rev:
        raise HTTPException(409, detail='行程已更新，请刷新后重试')
    payload = copy.deepcopy(rec.get('payload') or {})
    days = payload.get('itinerary') or []
    if req.day > len(days):
        raise HTTPException(422, detail='行程中没有这一天')
    try:
        days[req.day - 1] = retime(days[req.day - 1], req.start, req.end)
    except ValueError as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    _rebuild_transits(payload)
    if req.preview:
        return {'rev': req.rev, 'data': payload, 'warning': '时间平移保留所有活动与间隔；请核对营业时间、预约及真实班次，交通起止可能超出游览时间。'}
    _consume('edit', request)
    # Existing writer handles atomic revision checks, history, transport and budget.
    _write_itinerary(result_id, req.rev, days)
    fresh = get_travel_plan_store().get(result_id) or {}
    _schedule_review(result_id)
    return {'rev': fresh.get('rev', 0), 'data': {**(fresh.get('payload') or {}), 'review_stale': True}}
