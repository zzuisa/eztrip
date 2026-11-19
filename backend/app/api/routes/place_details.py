"""地点详情（评论 / 星标 / 营业时间）接口：用户打开地点详情时按需取。"""

from __future__ import annotations

import asyncio
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request

from ...services.guest_guard import client_ip, get_quota, is_owner, limits as guest_limits
from ...services.place_details_service import cache_key, get_place_details_service

router = APIRouter(prefix="/travel-plan", tags=["PlaceDetails"])

GLOBAL_KEY_IP = "all"


@router.get("/place-details", summary="地点评论 / 星标 / 营业时间（Google，按需 + 缓存）")
async def place_details(
    request: Request,
    name: str = Query(..., min_length=1, max_length=120),
    city: str = Query("", max_length=60),
    lat: Optional[float] = Query(None, ge=-90, le=90),
    lng: Optional[float] = Query(None, ge=-180, le=180),
    place_id: str = Query("", max_length=200),
):
    svc = get_place_details_service()
    key = cache_key(name, lat, lng, place_id)
    hit = svc.peek(key)
    if hit is not None:  # 命中缓存：不计费、不占额度
        return {"success": True, "available": hit["data"] is not None, "cached": True, "data": hit["data"]}

    q, ip, lim = get_quota(), client_ip(request), guest_limits()
    owner = is_owner(request)
    taken_user = taken_global = False
    if not owner:
        try:
            q.consume("pdetail", ip, lim["pdetail"])
            taken_user = True
        except HTTPException:
            return {"success": True, "available": False, "reason": "quota", "data": None}
        try:
            q.consume("pdetail_all", GLOBAL_KEY_IP, lim["pdetail_all"])
            taken_global = True
        except HTTPException:
            q.refund("pdetail", ip)
            return {"success": True, "available": False, "reason": "busy", "data": None}
    try:
        data = await asyncio.to_thread(svc.lookup, name, city, lat, lng, place_id)
    except Exception as e:  # noqa: BLE001
        print(f"[place-details] error {type(e).__name__}: {e}")
        if taken_user:
            q.refund("pdetail", ip)
        if taken_global:
            q.refund("pdetail_all", GLOBAL_KEY_IP)
        raise HTTPException(status_code=502, detail="暂时无法获取地点评论")
    return {"success": True, "available": data is not None, "cached": False, "data": data}


# Related public note cards are separate from the itinerary's adopted citations.
from typing import Literal


def _saved_place(result_id,day,kind,name):
    from ...services.travel_plan_store import get_travel_plan_store
    record=get_travel_plan_store().get(result_id)
    if not record:raise HTTPException(404,'行程不存在')
    payload=record.get('payload') or {};days=payload.get('itinerary') or []
    if day>len(days):raise HTTPException(404,'行程中没有这一天')
    selected=next((p for p in days[day-1].get('meals' if kind=='meal' else 'activities',[]) if str(p.get('name') or '').strip()==name.strip()),None)
    if not selected:raise HTTPException(404,'该地点不在当前行程中')
    city=str(days[day-1].get('city') or payload.get('location') or '')[:60]
    return selected,city


def _xhs_quota(request):
    if is_owner(request):return None
    q=get_quota();ip=client_ip(request);lim=guest_limits()
    try:q.consume('xhsplace',ip,lim['xhsplace'])
    except HTTPException:return 'quota'
    try:q.consume('xhsplace_all',GLOBAL_KEY_IP,lim['xhsplace_all'])
    except HTTPException:
        q.refund('xhsplace',ip);return 'busy'
    return None


@router.get('/results/{result_id}/place-inspiration',summary='行程地点的相关小红书攻略（按需缓存）')
async def place_inspiration(result_id:str,request:Request,day:int=Query(...,ge=1,le=30),kind:Literal['attraction','meal']='attraction',name:str=Query(...,min_length=1,max_length=120)):
    from ...config import get_settings
    from ...services.place_inspiration import get_place_inspiration_service
    from ...services.xiaohongshu_service import XiaohongshuError
    selected,city=_saved_place(result_id,day,kind,name)
    if not get_settings().enable_xiaohongshu_mcp:return {'status':'disabled','notes':[]}
    svc=get_place_inspiration_service();data=svc.peek(name,city)
    if data is None:
        limited=_xhs_quota(request)
        if limited:return {'status':limited,'notes':[]}
        try:data=await asyncio.to_thread(svc.lookup,name,city)
        except XiaohongshuError as error:return {'status':error.code,'notes':[]}
        except Exception:return {'status':'unavailable','notes':[]}
    else:data={**data,'cached':True}
    adopted={n.get('id') for n in selected.get('xhs_sources') or []}
    return {**data,'notes':[{**n,'adopted':n['id'] in adopted} for n in data.get('notes',[])]}


@router.get('/results/{result_id}/place-inspiration/{note_id}',summary='已搜索到的攻略短摘录')
async def place_inspiration_preview(result_id:str,note_id:str,request:Request,day:int=Query(...,ge=1,le=30),kind:Literal['attraction','meal']='attraction',name:str=Query(...,min_length=1,max_length=120)):
    from ...services.place_inspiration import get_place_inspiration_service
    from ...services.xiaohongshu_service import XiaohongshuError
    from ...config import get_settings
    selected,city=_saved_place(result_id,day,kind,name)
    if not get_settings().enable_xiaohongshu_mcp:return {'status':'disabled','excerpt':''}
    svc=get_place_inspiration_service();hit=svc.peek(name,city)
    if not hit:return {'status':'expired','excerpt':''}
    if note_id not in {n['id'] for n in hit.get('notes',[])}:raise HTTPException(404,'该笔记不在此地点的搜索结果中')
    # Cached preview calls are cheap; service checks its private packet before upstream access.
    packet=svc._read(svc.key(name,city))
    if note_id not in (packet or {}).get('previews',{}):
        limited=_xhs_quota(request)
        if limited:return {'status':limited,'excerpt':''}
    try:return await asyncio.to_thread(svc.preview,name,city,note_id)
    except XiaohongshuError as error:return {'status':error.code,'excerpt':''}
    except Exception:return {'status':'unavailable','excerpt':''}
