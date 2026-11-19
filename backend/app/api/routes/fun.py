"""找点乐子接口：附近的饭店 / 本地小馆 / 喝一杯 / 娱乐 / 咖啡甜点 / 近期活动。

费用与滥用防护：场所结果缓存 30 分钟（命中不计费不占额度）；未命中时游客按人计每日额度，并叠加全站每日上限；
站长不受限。活动只来自真实数据源（Ticketmaster），没配置 key 时如实返回 available=false，不让 LLM 编造。
"""

from __future__ import annotations

import asyncio
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse

from ...services import fun_service as fs
from ...services.guest_guard import client_ip, get_quota, is_owner, limits as guest_limits

router = APIRouter(prefix="/fun", tags=["Fun"])

GLOBAL_KEY_IP = "all"


@router.get("/categories", summary="可选类别")
async def categories():
    return {"success": True, "items": [{"key": k, "label": v["label"]} for k, v in fs.CATEGORIES.items()]}


@router.get("/places", summary="附近场所（Google Places，缓存 + 额度）")
async def places(
    request: Request,
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
    category: str = Query("eat", max_length=20),
    radius: int = Query(1500, ge=300, le=fs.MAX_RADIUS_M),
    sort: str = Query("smart", pattern="^(smart|distance|rating)$"),
    open_now: bool = Query(False),
    q: str = Query("", max_length=60),
):
    q = " ".join(q.split())
    if category not in fs.CATEGORIES and not q:
        raise HTTPException(status_code=400, detail="未知类别")
    svc = fs.get_fun_service()
    radius = fs.clamp_radius(radius)
    cat = fs.CATEGORIES.get(category) or {}
    max_ratings = cat.get("max_ratings") if not q else None

    raw = svc.peek_places(lat, lng, category, radius, q)
    cached = raw is not None
    if raw is None:
        quota, ip, lim = get_quota(), client_ip(request), guest_limits()
        taken_user = taken_global = False
        if not is_owner(request):
            try:
                quota.consume("fun", ip, lim["fun"])
                taken_user = True
            except HTTPException:
                return {"success": True, "available": False, "reason": "quota", "items": []}
            try:
                quota.consume("fun_all", GLOBAL_KEY_IP, lim["fun_all"])
                taken_global = True
            except HTTPException:
                quota.refund("fun", ip)
                return {"success": True, "available": False, "reason": "busy", "items": []}
        try:
            raw = await asyncio.to_thread(svc.fetch_places, lat, lng, category, radius, q)
        except Exception as e:  # noqa: BLE001
            print(f"[fun] places error {type(e).__name__}: {e}")
            if taken_user:
                quota.refund("fun", ip)
            if taken_global:
                quota.refund("fun_all", GLOBAL_KEY_IP)
            raise HTTPException(status_code=502, detail="暂时无法获取附近的地点，请稍后再试")

    items = fs.sort_items(fs.decorate(raw, lat, lng, radius, open_now=open_now, max_ratings=max_ratings), sort)
    return {"success": True, "available": True, "cached": cached, "category": category, "radius": radius, "items": items}


@router.get("/events", summary="近期活动（Ticketmaster；未配置时 available=false）")
async def events(
    request: Request,
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
    radius_km: int = Query(30, ge=3, le=100),
    days: int = Query(14, ge=1, le=60),
    q: str = Query("", max_length=40),
):
    svc = fs.get_fun_service()
    if not svc.events_key_configured():
        return {"success": True, "available": False, "reason": "no_source", "items": []}
    quota, ip, lim = get_quota(), client_ip(request), guest_limits()
    if not is_owner(request):
        try:
            quota.consume("fun", ip, lim["fun"])
        except HTTPException:
            return {"success": True, "available": False, "reason": "quota", "items": []}
    try:
        items = await asyncio.to_thread(svc.fetch_events, lat, lng, radius_km, days, " ".join(q.split()))
    except Exception as e:  # noqa: BLE001
        print(f"[fun] events error {type(e).__name__}: {e}")
        raise HTTPException(status_code=502, detail="暂时无法获取近期活动")
    return {"success": True, "available": True, "items": items}


@router.get("/photo", summary="场所图片（代理 Google Place Photo，落盘缓存）")
async def photo(request: Request, ref: str = Query(..., max_length=1400), w: int = Query(480, ge=120, le=960)):
    if not fs.valid_photo_ref(ref):
        raise HTTPException(status_code=400, detail="bad ref")
    w = int(round(w / 120.0)) * 120
    svc = fs.get_fun_service()
    path = svc.photo_cached(ref, w)
    if path is None:
        lim = guest_limits()
        if not is_owner(request):
            get_quota().consume("funphoto", client_ip(request), lim["funphoto"])
        try:
            get_quota().consume("funphoto_all", "all", lim["funphoto_all"])
        except HTTPException:
            raise HTTPException(status_code=404, detail="no photo")  # 全站总闸：前端会显示占位图
        path = await asyncio.to_thread(svc.fetch_photo, ref, w)
    if path is None:
        raise HTTPException(status_code=404, detail="no photo")
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=604800, immutable"})
