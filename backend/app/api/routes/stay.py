"""住宿推荐：为整趟行程推荐“住哪一片”并给出真实候选酒店。

- GET  /api/travel-plan/{id}/stay  读取已生成的推荐（不耗额度；返回 stale 表示行程之后又被编辑过）
- POST /api/travel-plan/{id}/stay  生成（游客占 stay 额度 + 全站每日上限；已有且未过期直接返回；force 仅行程编辑者可用）
推荐保存在行程 payload["stay"]，之后任何设备打开都直接可看。
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request, Query, Body
from pydantic import BaseModel, Field

from ...services import budget as budget_svc
from ...services import stay_advisor as sa
from ...services import stay_plan as sp
from ...services import stay_blocks as sb
from ...services import transit_plan as transit_svc
from ...services.guest_guard import client_ip, get_quota, is_owner, limits as guest_limits
from ...services.identity import can_edit
from ...services.travel_plan_store import get_travel_plan_store
from .itinerary_edit import _complete, edit_model

router = APIRouter(prefix="/travel-plan", tags=["Stay"])

_gen_lock = asyncio.Lock()
GLOBAL_IP = "all"


def _record(result_id: str) -> Dict[str, Any]:
    rec = get_travel_plan_store().get(result_id)
    if not rec:
        raise HTTPException(status_code=404, detail="记录不存在")
    return rec


def _stale(rec: Dict[str, Any], stay: Dict[str, Any] | None) -> bool:
    return bool(stay) and int(stay.get("rev", 0)) != int(rec.get("rev", 0))


@router.get('/hotels/search', summary='在所选片区查询具体酒店')
async def search_hotels(
    request: Request,
    q: str = Query('', max_length=80),
    city: str = Query('', max_length=60),
    lat: Optional[float] = Query(None, ge=-90, le=90),
    lng: Optional[float] = Query(None, ge=-180, le=180),
    travelers: int = Query(1, ge=1, le=20),
    rooms: Optional[int] = Query(None, ge=1, le=20),
):
    from . import itinerary_edit
    if (lat is None) != (lng is None):
        raise HTTPException(422, detail='请提供完整的片区坐标')
    if not q.strip() and not city.strip():
        raise HTTPException(422, detail='请选择城市或输入酒店名称')
    itinerary_edit._consume('psearch', request)
    from ...services.party import counts
    if rooms and rooms > travelers:raise HTTPException(422, detail='房间数不能超过同行人数')
    party=counts({'travelers':travelers,'rooms':rooms})
    anchor = (lat, lng) if lat is not None else None
    try:
        raw = await asyncio.to_thread(sa.get_hotel_search().search,
            f'{city} {q}'.strip(), f"酒店 hotel {travelers} adults {party['rooms']} rooms"+(' family room apartment' if travelers>2 else ''), anchor, 6000)
        # Require an accommodation type, never relabel arbitrary places as hotels.
        raw = [p for p in raw if set(p.get('types') or []) & {
            'lodging', 'hotel', 'motel', 'resort_hotel', 'extended_stay_hotel',
            'bed_and_breakfast', 'guest_house', 'hostel', 'inn'}]
        if anchor:
            raw = [p for p in raw if (loc := p.get('location') or {}).get('latitude') is not None
                   and loc.get('longitude') is not None
                   and sa.km(anchor, (loc['latitude'],loc['longitude'])) <= 12]
        points = [{'lat':anchor[0], 'lng':anchor[1], 'day':1}] if anchor else [
            {'lat':loc['latitude'], 'lng':loc['longitude'], 'day':1}
            for p in raw if (loc := p.get('location') or {}).get('latitude') is not None and loc.get('longitude') is not None]
        hotels = sa.rank_hotels(raw, points, limit=8) if points else []
        if not anchor:
            for h in hotels:
                h.pop('avg_km',None)
        return {'items':hotels, 'source':'Google Places', 'availability_checked':False, 'party':party}
    except Exception:
        raise HTTPException(502, detail='酒店查询暂时不可用，请稍后重试或更换酒店名称')


@router.get('/hotels/quote', summary='查询具体酒店的多人入住报价')
async def quote_hotel(request: Request, hotel_name: str = Query(..., min_length=1,max_length=120),
                      city: str = Query('',max_length=60), check_in: str = Query('',max_length=10),
                      check_out: str = Query('',max_length=10), travelers: int = Query(1,ge=1,le=20),
                      rooms: Optional[int] = Query(None,ge=1,le=20)):
    from .itinerary_edit import _consume
    from ...services.party import counts
    if rooms and rooms>travelers:raise HTTPException(422,detail='房间数不能超过同行人数')
    _consume('psearch',request)
    party=counts({'travelers':travelers,'rooms':rooms})
    q=await budget_svc._acall('hotel_quote',{'hotel_name':hotel_name,'city':city,'check_in':check_in,'check_out':check_out,
                                          'adults':travelers,'rooms':party['rooms']})
    meta={'start_date':check_in,'end_date':check_out}
    if not budget_svc._verified_price(q,meta,party):
        return {'ok':False,'reason':q.get('reason') or 'unverified_quote','party':party,
                'note':'暂未获取匹配日期与人数的报价，可继续选择酒店，预算将标明参考估算。'}
    return q


@router.get("/{result_id}/stay", summary="读取已生成的住宿推荐")
async def get_stay(result_id: str):
    rec = _record(result_id)
    stay = (rec.get("payload") or {}).get("stay")
    return {"stay": stay, "stale": _stale(rec, stay)}


@router.get('/{result_id}/stay-plan', summary='按城市连住的住宿分段建议（只读）')
async def get_stay_plan(result_id: str):
    rec = _record(result_id)
    from ...agents import final_review
    payload=rec.get('payload') or {}
    from ...services.party import counts
    return {'party':counts(payload.get('trip_meta') or {}),**sb.propose(payload,int(rec.get('rev') or 0)), 'review_in_progress':result_id in final_review._IN_FLIGHT, 'review_stale':final_review.needs_review(payload)}


@router.post('/{result_id}/stay-plan/{block_id}/recommend', summary='只推荐当前住宿分段的片区')
async def recommend_stay_block(result_id: str, block_id: str, request: Request):
    rec = _record(result_id);payload = rec.get('payload') or {};rev = int(rec.get('rev') or 0)
    proposal = sb.propose(payload, rev)
    block = next((b for b in proposal['blocks'] if b['id'] == block_id), None)
    if not block: raise HTTPException(404, detail='住宿分段已变化，请重新载入')
    cached = (payload.get('stay_recommendations') or {}).get(block_id)
    if cached and cached.get('rev') == rev and cached.get('city') == block['city']:
        return {'areas': [c for a in cached.get('areas') or [] if (c := sb.area_choice(a,block['center']))], 'cached':True}
    view = {**payload, 'location':block['city'], 'itinerary':[payload['itinerary'][i] for i in block['day_indices']], 'days':len(block['day_indices'])}
    points = sa.collect_points(view)
    points = [p for p in points if block['center'] and sa.km(tuple(block['center']), (p['lat'],p['lng'])) < 55]
    if len(points)<2: raise HTTPException(422, detail='这一段可用地点不足，请自行搜索酒店或选择游览中心附近')
    owner,ip,lim,q = is_owner(request),client_ip(request),guest_limits(),get_quota()
    took=[]
    session=hashlib.sha256(f'{ip}:{rev}'.encode()).hexdigest()[:24]
    new_session=session not in (rec.get('stay_sessions') or [])
    if not owner:
        try:
            if new_session:q.consume('stay',ip,lim['stay']);took.append(('stay',ip))
            q.consume('stay_all',GLOBAL_IP,lim['stay_all']);took.append(('stay_all',GLOBAL_IP))
        except HTTPException:
            for k,key in took:q.refund(k,key)
            raise
    try:
        async with _gen_lock:
            report = await _build(view,points,str((payload.get('trip_meta') or {}).get('accommodation') or ''))
        report.update(rev=rev,city=block['city'])
        def save(r):
            if int(r.get('rev') or 0)!=rev:return False
            r.setdefault('payload',{}).setdefault('stay_recommendations',{})[block_id]=report
            if not owner:
                sessions=r.setdefault('stay_sessions',[])
                if session not in sessions:sessions.append(session)
                del sessions[:-32]
            return True
        if not get_travel_plan_store().update_record(result_id,save):raise HTTPException(409,detail='行程已变化，请重新载入')
        return {'areas':[c for a in report['areas'] if (c:=sb.area_choice(a,block['center']))], 'summary':report['summary'],'cached':False}
    except Exception as e:
        for k,key in took:q.refund(k,key)
        if isinstance(e,HTTPException):raise
        raise HTTPException(502,detail='片区推荐暂时不可用，可先选已有区域或自行搜索')


async def _build(payload: Dict[str, Any], points: List[Dict[str, Any]], pref: str) -> Dict[str, Any]:
    ai = None
    for _ in range(2):
        ai = sa.parse_areas(await _complete(sa.build_messages(payload, points, pref)))
        if ai:
            break
    if not ai:
        raise RuntimeError("AI 返回格式不合格")
    center = sa.centroid(points)
    spread_m = max(sa.km(center, (p["lat"], p["lng"])) for p in points) * 1000
    kw = sa.keyword_for(pref)
    search = sa.get_hotel_search()

    async def one(area: Dict[str, Any]) -> Dict[str, Any]:
        try:
            places = await asyncio.to_thread(search.search, area["query"], kw, center, spread_m + 6000)
        except Exception as e:  # noqa: BLE001
            print(f"[stay] hotel search failed area={area['name']!r} {type(e).__name__}: {e}")
            places = []
        hotels = sa.rank_hotels(places, points)
        return {**area, "hotels": hotels, "stats": sa.area_stats(hotels, points)}

    areas = await asyncio.gather(*(one(a) for a in ai["areas"]))
    scored = [a for a in areas if a["stats"]]
    if scored:  # 标出离整趟行程最近的片区
        min(scored, key=lambda a: a["stats"]["avg_km"])["closest"] = True
    return {"summary": ai["summary"], "areas": areas}


@router.post("/{result_id}/stay", summary="生成住宿推荐（AI 片区 + Google 酒店）")
async def make_stay(result_id: str, request: Request, force: bool = False, pref: str = "", seg: int = -1):
    rec = _record(result_id)
    payload = rec.get("payload") or {}
    stay = payload.get("stay")
    if force and not can_edit(request, rec):
        force = False
    pref = sa.clean_pref(pref)
    segs = budget_svc.segments_of(payload)
    view = payload
    if segs:  # 多城市行程：一次只为其中一座城市推荐住宿
        seg = seg if 0 <= seg < len(segs) else 0
        days_ = [d for d in (payload.get("itinerary") or []) if isinstance(d, dict) and int(d.get("segment", 0)) == seg]
        view = {**payload, "location": segs[seg]["city"], "itinerary": days_, "days": len(days_)}
        if stay and int(stay.get("seg", 0)) != seg and can_edit(request, rec):
            force = True
    else:
        seg = -1
    if pref and stay and pref != str(stay.get("pref") or "") and can_edit(request, rec):
        force = True  # 偏好变了：重新生成
    if stay and not force and not _stale(rec, stay):
        return {"stay": stay, "stale": False, "cached": True}
    if stay and not force:  # 过期但没要求重生成：直接返回旧的，由前端提示“行程已改，可重新生成”
        return {"stay": stay, "stale": True, "cached": True}
    points = sa.collect_points(view)
    if len(points) < 2:
        raise HTTPException(status_code=422, detail="行程里还没有足够的带位置的地点，暂时无法推荐住宿")

    owner, ip, lim, q = is_owner(request), client_ip(request), guest_limits(), get_quota()
    took_user = took_all = False
    if not owner:
        q.consume("stay", ip, lim["stay"])
        took_user = True
        try:
            q.consume("stay_all", GLOBAL_IP, lim["stay_all"])
            took_all = True
        except HTTPException:
            q.refund("stay", ip)
            raise HTTPException(status_code=503, detail="住宿推荐今天访问量较大，请明天再试，或输入访问口令")
    try:
        async with _gen_lock:
            meta = payload.get("trip_meta") or {}
            pref = pref or str(meta.get("accommodation") or "")
            body = await _build(view, points, pref)
        body.update({
            "v": 1, "generated_at": int(time.time()), "rev": int(rec.get("rev", 0)), "model": edit_model(), "pref": pref,
            "seg": seg, "trip": {"city": view.get("location", ""), "start_date": meta.get("start_date", ""), "end_date": meta.get("end_date", "")},
        })
        get_travel_plan_store().update_payload(result_id, lambda p: p.__setitem__("stay", body))
        return {"stay": body, "stale": False, "cached": False}
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        print(f"[stay] error {type(e).__name__}: {e}")
        if took_user:
            q.refund("stay", ip)
        if took_all:
            q.refund("stay_all", GLOBAL_IP)
        raise HTTPException(status_code=502, detail="暂时无法生成住宿推荐，请稍后重试")



# ---------------------------------------------------------------- 选定/更换住宿 → 重排路线 + 重算预算


from ...models.schemas import NightStay


class SetStayReq(BaseModel):
    blocks: Optional[List[Dict[str, Any]]] = Field(default=None, max_length=14)
    stays: Optional[List[NightStay]] = None
    stay_name: str = Field(default="", max_length=120)
    stay_lat: Optional[float] = Field(default=None, ge=-90, le=90)
    stay_lng: Optional[float] = Field(default=None, ge=-180, le=180)
    reorder: bool = True  # 只调整每天景点的先后顺序（地点不增不减）；False=只重算预算
    rev: int = 0


@router.post("/{result_id}/stay-set", summary="选定/更换住宿：按住宿重排每天顺序并重算预算（不重新生成、不耗模型）")
async def set_stay(result_id: str, req: SetStayReq, request: Request):
    from .itinerary_edit import HISTORY_KEEP, _consume, _require_editor

    rec = _record(result_id)
    _require_editor(request, rec)
    payload = rec.get("payload") or {}
    if int(rec.get('rev') or 0)!=req.rev:
        raise HTTPException(409,detail={'code':'rev_conflict','message':'行程已在别处修改，请重新载入','rev':rec.get('rev',0)})
    block_meta = None
    if req.blocks is not None:
        try:
            expanded,block_meta=sb.expand(req.blocks,max(0,len(payload.get('itinerary') or [])-1))
            if req.stays is not None and [x.model_dump() for x in req.stays]!=expanded:
                raise ValueError('住宿分段与每晚记录不一致，请重新选择')
            req.stays=[NightStay(**x) for x in expanded]
        except (ValueError,TypeError) as e:raise HTTPException(422,detail=str(e))
    name = sp.clean_stay(req.stay_name)
    if name and (req.stay_lat is None or req.stay_lng is None):
        raise HTTPException(status_code=422, detail="请从搜索结果里选择住宿位置")
    meta = dict(payload.get("trip_meta") or {})
    for k in ("stay_name", "stay_lat", "stay_lng"):
        meta.pop(k, None)
    if name:
        meta.update({"stay_name": name, "stay_lat": req.stay_lat, "stay_lng": req.stay_lng})
    itinerary = payload.get("itinerary") or []
    if req.stays is not None:
        nights = [x.night for x in req.stays]
        if len(nights) != len(set(nights)) or sorted(nights) != list(range(1, len(itinerary))):
            raise HTTPException(422, detail='请确认每一晚的酒店或住宿区域')
        meta['stays'] = [x.model_dump() for x in req.stays]
        meta['stay_status'] = 'confirmed'
        if block_meta is not None:meta['stay_blocks']=block_meta
        else:meta.pop('stay_blocks',None)
    else:
        meta.pop('stays', None)
        meta.pop('stay_blocks',None)
        meta['stay_status'] = 'confirmed' if name or len(itinerary) <= 1 else 'pending'
    report: List[Dict[str, Any]] = []
    new_it = copy.deepcopy(itinerary)
    if name and req.reorder:
        new_it, report = sp.reorder_itinerary(itinerary, (req.stay_lat, req.stay_lng))
    _consume("edit",request)
    old_budget = payload.get("total_budget") or {}
    bud = await budget_svc.build_budget({**payload, "itinerary": new_it}, meta)
    state: Dict[str, Any] = {}

    def mut(r: Dict[str, Any]) -> bool | None:
        if int(r.get("rev") or 0) != req.rev:
            state["conflict"] = int(r.get("rev") or 0)
            return False
        p = r.setdefault("payload", {})
        old = copy.deepcopy(p.get("itinerary") or [])
        r.setdefault("original", old)
        h = r.setdefault("history", [])
        h.append({"rev": int(r.get("rev") or 0), "at": int(time.time()), "itinerary": old})
        del h[:-HISTORY_KEEP]
        p["itinerary"] = new_it
        if p.get("story"):
            p["story_stale"] = True
        r["rev"] = int(r.get("rev") or 0) + 1
        p["trip_meta"] = meta
        p["total_budget"] = bud
        transit_svc.copy_transits(new_it, p.get("itinerary") or [])
        state["rev"] = int(r.get("rev") or 0)
        return True

    if not get_travel_plan_store().update_record(result_id, mut):
        if "conflict" in state:
            raise HTTPException(status_code=409, detail={"code": "rev_conflict", "message": "行程已在别处修改，请刷新后再试", "rev": state["conflict"]})
        raise HTTPException(status_code=404, detail="记录不存在")
    from .itinerary_edit import _schedule_review
    _schedule_review(result_id)
    return {"success": True, "rev": state["rev"], "trip_meta": meta, "total_budget": bud, "diff": budget_svc.diff_budget(old_budget, bud),
            "transits": transit_svc.snapshot(new_it), "reordered": report, "itinerary": new_it if report else None}


class BudgetPartyUpdate(BaseModel):
    travelers: Optional[int] = Field(None,ge=1,le=20)
    rooms: Optional[int] = Field(None,ge=1,le=20)
    vehicle_count: Optional[int] = Field(None,ge=1,le=20)
    rev: Optional[int] = Field(None,ge=0)


@router.post("/{result_id}/budget/refresh", summary="按人数、房间数和车型数量重算人均预算")
async def refresh_budget(result_id: str, request: Request, options: Optional[BudgetPartyUpdate] = Body(None)):
    from .itinerary_edit import _consume, _require_editor
    rec=_record(result_id);_require_editor(request,rec)
    rev=int(rec.get('rev') or 0)
    if options and options.rev is not None and options.rev!=rev:raise HTTPException(409,detail='行程已变化，请刷新后再试')
    payload=copy.deepcopy(rec.get('payload') or {});old_meta=payload.get('trip_meta') or {};meta=dict(old_meta)
    if options:
        if 'travelers' in options.model_fields_set and options.travelers is None:raise HTTPException(422,detail='请选择同行人数')
        updates=options.model_dump(exclude_unset=True,exclude={'rev'})
        meta.update(updates)
        if 'travelers' in updates:
            for key in ('rooms','vehicle_count'):
                if key not in updates:meta.pop(key,None)
    from ...services.party import counts
    party=counts(meta)
    if meta.get('rooms') and meta['rooms']>party['travelers']:raise HTTPException(422,detail='房间数不能超过同行人数')
    if party['vehicles'] and meta.get('vehicle_count') and meta['vehicle_count']*5<party['travelers']:
        raise HTTPException(422,detail='车辆按5座估算，请增加车辆数量')
    _consume('edit',request)
    old_budget=payload.get('total_budget') or {};bud=await budget_svc.build_budget(payload,meta)
    state={};changed=meta!=old_meta
    def persist(r):
        if int(r.get('rev') or 0)!=rev:return False
        p=r.setdefault('payload',{});p['total_budget']=bud;p['trip_meta']=meta
        transit_svc.copy_transits(payload.get('itinerary') or [],p.get('itinerary') or [])
        if changed:r['rev']=rev+1
        state['rev']=int(r.get('rev') or 0)
        return True
    if not get_travel_plan_store().update_record(result_id,persist):raise HTTPException(409,detail='查价期间行程已变化，请刷新后再试')
    return {'success':True,'rev':state['rev'],'trip_meta':meta,'total_budget':bud,
            'transits':transit_svc.snapshot(payload.get('itinerary') or []),'diff':budget_svc.diff_budget(old_budget,bud)}
