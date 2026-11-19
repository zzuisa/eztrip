"""城际路段「路线对比」：公共交通（逐段月票判定 + 票价）与自驾的多方案对比，选定后写回路段与预算。

- GET  /api/travel-plan/{id}/route-compare   已保存的对比结果（不耗额度）
- POST /api/travel-plan/{id}/route-compare   生成对比（调 Google Routes，付费：游客占 rcmp 额度 + 全站每日上限；结果只在行程编辑者发起时保存）
- POST /api/travel-plan/{id}/route-choose    选定某个方案（或清除选择）→ 路段与预算按它重算；仅行程编辑者
价格/月票判断全部来自 travel_prices MCP（代码），顾问文案由 agents.route_advisor 生成并校验。
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any, Dict, Literal

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ...agents import route_advisor
from ...services import budget as budget_svc
from ...services import route_compare as rc
from ...services import transit_plan as transit_svc
from ...services.guest_guard import client_ip, get_quota, is_owner, limits as guest_limits
from ...services.identity import can_edit
from ...services.llm_service import get_llm_router
from ...services.model_config import get_model
from ...services.travel_plan_store import get_travel_plan_store

router = APIRouter(prefix="/travel-plan", tags=["RouteCompare"])

_lock = asyncio.Lock()
GLOBAL_IP = "all"
ERRORS = {"no_key": "路线服务尚未配置", "daily_cap": "今天的路线查询已达上限，请明天再试", "no_routes": "没有找到可用的路线"}


def _record(result_id: str) -> Dict[str, Any]:
    rec = get_travel_plan_store().get(result_id)
    if not rec:
        raise HTTPException(status_code=404, detail="记录不存在")
    return rec


async def _complete(messages) -> str:
    r = get_llm_router()
    if not r.api_key:
        raise RuntimeError("LLM 未配置")
    body = {"model": get_model("route_advice"), "messages": messages, "temperature": 0.2, "max_tokens": 300, **r._extra()}
    async with httpx.AsyncClient(timeout=httpx.Timeout(connect=8.0, read=30.0, write=10.0, pool=8.0)) as c:
        resp = await c.post(f"{r.base_url}/chat/completions", headers={"Authorization": f"Bearer {r.api_key}", "Content-Type": "application/json"}, json=body)
    if resp.status_code >= 400:
        raise RuntimeError(f"upstream {resp.status_code}")
    return (((resp.json().get("choices") or [{}])[0]).get("message") or {}).get("content") or ""


class CompareReq(BaseModel):
    day: int = Field(ge=1, le=60)
    kind: Literal["transit_start", "transit_end"]
    ticket: Literal["d_ticket", "none"] = "d_ticket"
    bahncard: Literal[0, 25, 50] = 0
    passengers: int | None = Field(default=None, ge=1, le=8)
    fuel: Literal["petrol", "diesel", "hybrid", "electric"] = "petrol"
    consumption: float = Field(default=0.0, ge=0, le=40)
    force: bool = False


class ChooseReq(BaseModel):
    day: int = Field(ge=1, le=60)
    kind: Literal["transit_start", "transit_end"]
    option_id: str = Field(default="", max_length=8)   # 空 = 清除选择，回到里程估算


@router.get("/{result_id}/route-compare", summary="读取已保存的路线对比")
async def get_compare(result_id: str):
    rec = _record(result_id)
    p = rec.get("payload") or {}
    return {'travelers':int((p.get('trip_meta') or {}).get('travelers') or 1),'choice_parties':{k:(v.get('opt') or {}).get('passengers') for k,v in (p.get('route_choices') or {}).items() if isinstance(v,dict)},'coverage':'ground_only','coverage_note':'此处仅比较火车/巴士等地面公共交通与自驾，不包含已核实航班；地面长途不要自动改成飞机。',"compare": p.get("route_compare") or {}, "choices": {k: (v.get("opt") or {}).get("id") for k, v in (p.get("route_choices") or {}).items() if isinstance(v, dict)}}


@router.post("/{result_id}/route-compare", summary="生成路线对比（公共交通 vs 自驾）")
async def make_compare(result_id: str, req: CompareReq, request: Request):
    rec = _record(result_id)
    payload = rec.get("payload") or {}
    values=req.model_dump();values['passengers']=req.passengers or min(8,int((payload.get('trip_meta') or {}).get('travelers') or 1))
    prefs = rc.clean_prefs(values)
    try:
        _, leg = rc.find_leg(payload, req.day, req.kind)
    except rc.CompareError as e:
        raise HTTPException(status_code=422, detail=str(e))
    key, sig = rc.key_of(req.day, req.kind), rc.sig_of(leg)
    editor = can_edit(request, rec)
    stored = (payload.get("route_compare") or {}).get(key)
    if stored and not req.force and stored.get("prefs") == prefs and stored.get("sig") == sig:
        return {"item": stored, "cached": True}

    owner, ip, lim, q = is_owner(request), client_ip(request), guest_limits(), get_quota()
    took_user = took_all = False
    if not owner:
        q.consume("rcmp", ip, lim["rcmp"])
        took_user = True
        try:
            q.consume("rcmp_all", GLOBAL_IP, lim["rcmp_all"])
            took_all = True
        except HTTPException:
            q.refund("rcmp", ip)
            raise HTTPException(status_code=503, detail="路线对比今天访问量较大，请明天再试，或输入访问口令")

    def refund() -> None:
        if took_user:
            q.refund("rcmp", ip)
        if took_all:
            q.refund("rcmp_all", GLOBAL_IP)

    try:
        async with _lock:
            result = await rc.fetch(rc.mcp_args(payload, req.day, req.kind, prefs))
        if not result.get("ok"):
            refund()
            raise HTTPException(status_code=502, detail=ERRORS.get(str(result.get("error") or ""), "暂时无法获取路线，请稍后再试"))
        result.setdefault('notes',[]).append('此处为地面交通对比，不含航班；费用按当前对比人数计算，长途可能跨天。')
        result['coverage']='ground_only'
        advice = await route_advisor.advise(result, leg, complete=_complete)
    except HTTPException:
        raise
    except rc.CompareError as e:
        refund()
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:  # noqa: BLE001
        print(f"[route-compare] error {type(e).__name__}: {e}")
        refund()
        raise HTTPException(status_code=502, detail="暂时无法获取路线，请稍后再试")
    item = {"v": 1, "day": req.day, "kind": req.kind, "at": int(time.time()), "sig": sig, "prefs": prefs, "rev": int(rec.get("rev", 0)),
            "result": result, "advice": advice}
    if editor:
        get_travel_plan_store().update_payload(result_id, lambda p: p.setdefault("route_compare", {}).__setitem__(key, item))
    return {"item": item, "cached": False, "saved": editor}


@router.post("/{result_id}/route-choose", summary="选定一个出行方案：路段与预算按它重算")
async def choose(result_id: str, req: ChooseReq, request: Request):
    from .itinerary_edit import _consume, _require_editor

    rec = _record(result_id)
    _require_editor(request, rec)
    _consume("edit", request)
    payload = rec.get("payload") or {}
    key = rc.key_of(req.day, req.kind)
    try:
        _, leg = rc.find_leg(payload, req.day, req.kind)
    except rc.CompareError as e:
        raise HTTPException(status_code=422, detail=str(e))
    choice = None
    if req.option_id:
        stored = (payload.get("route_compare") or {}).get(key)
        if not stored or stored.get("sig") != rc.sig_of(leg):
            raise HTTPException(status_code=409, detail="路线已变化，请重新对比")
        opt = next((o for o in (stored.get("result") or {}).get("options") or [] if o.get("id") == req.option_id), None)
        if not opt:
            raise HTTPException(status_code=422, detail="没有这个方案")
        travelers=int((payload.get('trip_meta') or {}).get('travelers') or 1)
        if opt.get('kind')=='transit' and travelers<=8 and int(opt.get('passengers') or 1)!=travelers:
            raise HTTPException(409,detail='对比人数与旅途同行人数不一致，请按当前人数重新查询')
        choice = {"sig": rc.sig_of(leg), "opt": rc.compact(opt), "at": int(time.time()), "prefs": stored.get("prefs")}

    def mut(p: Dict[str, Any]) -> None:
        ch = p.setdefault("route_choices", {})
        if choice:
            ch[key] = choice
        else:
            ch.pop(key, None)

    get_travel_plan_store().update_payload(result_id, mut)
    saved = get_travel_plan_store().get(result_id) or {}
    sp_ = saved.get("payload") or {}
    meta_ = dict(sp_.get("trip_meta") or {})
    budget_out = None
    transit_svc.build(sp_, meta_)
    if (sp_.get("total_budget") or {}).get("detail"):
        budget_out = await budget_svc.build_budget(sp_, meta_, reuse=sp_["total_budget"])
    transits_out = transit_svc.snapshot(sp_.get("itinerary") or [])

    def persist(p: Dict[str, Any]) -> None:
        if budget_out:
            p["total_budget"] = budget_out
        transit_svc.copy_transits(sp_.get("itinerary") or [], p.get("itinerary") or [])

    get_travel_plan_store().update_payload(result_id, persist)
    return {"success": True, "transits": transits_out, "total_budget": budget_out, "choice": (choice or {}).get("opt")}

