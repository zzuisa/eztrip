"""POI相关API路由"""

import asyncio

from fastapi import APIRouter, HTTPException, Depends, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from typing import List, Optional
from ...services.guest_guard import require_owner, is_owner, client_ip, get_quota, limits as guest_limits
from ...services.amap_service import get_amap_service
from ...services.poi_image_service import get_poi_image_service, make_key

router = APIRouter(prefix="/poi", tags=["POI"])


class POIDetailResponse(BaseModel):
    """POI详情响应"""
    success: bool
    message: str
    data: Optional[dict] = None


@router.get(
    "/detail/{poi_id}",
    dependencies=[Depends(require_owner)],
    response_model=POIDetailResponse,
    summary="获取POI详情",
    description="根据POI ID获取详细信息,包括图片"
)
async def get_poi_detail(poi_id: str):
    """
    获取POI详情
    
    Args:
        poi_id: POI ID
        
    Returns:
        POI详情响应
    """
    try:
        amap_service = get_amap_service()
        
        # 调用高德地图POI详情API
        result = amap_service.get_poi_detail(poi_id)
        
        return POIDetailResponse(
            success=True,
            message="获取POI详情成功",
            data=result
        )
        
    except Exception as e:
        print(f"❌ 获取POI详情失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"获取POI详情失败: {str(e)}"
        )


@router.get(
    "/search",
    dependencies=[Depends(require_owner)],
    summary="搜索POI",
    description="根据关键词搜索POI"
)
async def search_poi(keywords: str, city: str = "北京"):
    """
    搜索POI

    Args:
        keywords: 搜索关键词
        city: 城市名称

    Returns:
        搜索结果
    """
    try:
        amap_service = get_amap_service()
        result = amap_service.search_poi(keywords, city)

        return {
            "success": True,
            "message": "搜索成功",
            "data": result
        }

    except Exception as e:
        print(f"❌ 搜索POI失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"搜索POI失败: {str(e)}"
        )


@router.get(
    "/photo",
    summary="获取地点图片（Google Places → Wikipedia → Unsplash → 兜底）",
    description="返回本站代理的图片地址；未命中缓存的请求对游客计入 img 配额，超额只给兜底图（不报错）",
)
async def get_attraction_photo(
    request: Request,
    name: str = Query(..., min_length=1, max_length=120),
    city: str = Query("", max_length=80),
    address: str = Query("", max_length=200),
    lat: Optional[float] = Query(None, ge=-90, le=90),
    lng: Optional[float] = Query(None, ge=-180, le=180),
    kind: str = Query("attraction", max_length=16),
):
    svc = get_poi_image_service()
    kind = kind if kind in ("attraction", "meal", "hotel") else "attraction"
    key = make_key(name, lat, lng, kind)
    allow_remote = True
    if not svc.is_cached(key):
        lim = guest_limits()
        try:
            if not is_owner(request):
                get_quota().consume("img", client_ip(request), lim["img"])
            get_quota().consume("img_all", "all", lim["img_all"])  # 站长也受全站总闸约束，防止异常循环烧额度
        except HTTPException:
            allow_remote = False  # 超额：降级为兜底图，不打断页面
    res = await asyncio.to_thread(
        svc.resolve, name, city=city, address=address, lat=lat, lng=lng, kind=kind, allow_remote=allow_remote
    )
    meta = svc._read_meta(res["key"]) or {}
    return {
        "success": True,
        "message": "获取图片成功",
        "data": {
            "name": name,
            "photo_url": res["url"],
            "source": res["source"],
            "credit": meta.get("credit", ""),
            "link": meta.get("link", ""),
        },
    }


@router.get("/photo/img/{key}", summary="读取已缓存的地点图片")
async def get_cached_photo(key: str):
    found = get_poi_image_service().file_for(key)
    if not found:
        raise HTTPException(status_code=404, detail="图片不存在")
    path, mime = found
    return FileResponse(
        path,
        media_type=mime,
        headers={"Cache-Control": "public, max-age=86400, stale-while-revalidate=604800", "X-Content-Type-Options": "nosniff"},
    )
