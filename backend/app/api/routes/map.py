"""地图服务API路由"""

from fastapi import APIRouter, HTTPException, Query
from typing import Optional
from ...models.schemas import (
    POISearchRequest,
    POISearchResponse,
    RouteRequest,
    RouteResponse,
    WeatherResponse
)
from ...config import get_settings
from ...services.amap_service import get_amap_service
from ...services.mapbox_service import get_mapbox_service
from ...tools.debug_trace import dbg

router = APIRouter(prefix="/map", tags=["地图服务"])


@router.get(
    "/poi",
    response_model=POISearchResponse,
    summary="搜索POI",
    response_description="返回 POI 列表（含经纬度与地址）",
    description=(
        "根据关键词搜索 POI（兴趣点）。\n\n"
        "- `map_provider=mapbox` 时走 Mapbox MCP\n"
        "- 否则走高德地图 MCP"
    ),
    responses={
        200: {
            "description": "POI 搜索成功",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "POI搜索成功",
                        "data": [
                            {
                                "id": "poi.1",
                                "name": "上海迪士尼度假区",
                                "type": "poi",
                                "address": "上海市浦东新区川沙新镇黄赵路310号",
                                "location": {"longitude": 121.657, "latitude": 31.143},
                                "tel": None,
                                "mapbox_id": "mbx.123",
                            }
                        ],
                    }
                }
            },
        },
        500: {"description": "POI 搜索失败"},
    },
)
async def search_poi(
    keywords: str = Query(..., description="搜索关键词", example="故宫"),
    city: str = Query(..., description="城市", example="北京"),
    citylimit: bool = Query(True, description="是否限制在城市范围内")
):
    """
    搜索POI
    
    Args:
        keywords: 搜索关键词
        city: 城市
        citylimit: 是否限制在城市范围内
        
    Returns:
        POI搜索结果
    """
    try:
        dbg("收到前端 /map/poi 输入", {"keywords": keywords, "city": city, "citylimit": citylimit})
        settings = get_settings()
        service = get_mapbox_service() if (settings.map_provider or "amap").lower() == "mapbox" else get_amap_service()
        dbg("传入 map service.search_poi 的参数", {"keywords": keywords, "city": city, "citylimit": citylimit})
        
        # 搜索POI
        pois = service.search_poi(keywords, city, citylimit)
        dbg("map service.search_poi 返回(数量)", {"count": len(pois)})
        
        return POISearchResponse(
            success=True,
            message="POI搜索成功",
            data=pois
        )
        
    except Exception as e:
        print(f"❌ POI搜索失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"POI搜索失败: {str(e)}"
        )


@router.get(
    "/weather",
    response_model=WeatherResponse,
    summary="查询天气",
    response_description="返回天气数组；Mapbox 模式下返回空数组",
    description=(
        "查询指定城市天气。\n\n"
        "当 `map_provider=mapbox` 时，接口返回空数据并提示当前版本不提供天气。"
    ),
    responses={
        200: {
            "description": "天气查询结果",
            "content": {
                "application/json": {
                    "examples": {
                        "mapbox_mode": {
                            "summary": "Mapbox 模式（无天气能力）",
                            "value": {
                                "success": True,
                                "message": "当前版本不提供天气查询（Mapbox 模式）",
                                "data": [],
                            },
                        },
                        "amap_mode": {
                            "summary": "Amap 模式（正常返回天气）",
                            "value": {
                                "success": True,
                                "message": "天气查询成功",
                                "data": [
                                    {
                                        "date": "2026-05-01",
                                        "day_weather": "晴",
                                        "night_weather": "多云",
                                        "day_temp": 26,
                                        "night_temp": 19,
                                        "wind_direction": "东南风",
                                        "wind_power": "3级",
                                    }
                                ],
                            },
                        },
                    }
                }
            },
        },
        500: {"description": "天气查询失败"},
    },
)
async def get_weather(
    city: str = Query(..., description="城市名称", example="北京")
):
    """
    查询天气
    
    Args:
        city: 城市名称
        
    Returns:
        天气信息
    """
    try:
        settings = get_settings()
        if (settings.map_provider or "amap").lower() == "mapbox":
            return WeatherResponse(success=True, message="当前版本不提供天气查询（Mapbox 模式）", data=[])
        service = get_amap_service()
        
        # 查询天气
        weather_info = service.get_weather(city)
        
        return WeatherResponse(
            success=True,
            message="天气查询成功",
            data=weather_info
        )
        
    except Exception as e:
        print(f"❌ 天气查询失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"天气查询失败: {str(e)}"
        )


@router.post(
    "/route",
    response_model=RouteResponse,
    summary="规划路线",
    response_description="返回距离、时长和路线摘要",
    description=(
        "规划两点之间的路线。\n\n"
        "支持 `walking / driving / cycling`（部分 provider 可能将 transit 映射为 walking）。"
    ),
    responses={
        200: {
            "description": "路线规划成功",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "路线规划成功",
                        "data": {
                            "distance": 3250.5,
                            "duration": 2100,
                            "route_type": "walking",
                            "description": "recommended route",
                        },
                    }
                }
            },
        },
        500: {"description": "路线规划失败"},
    },
)
async def plan_route(request: RouteRequest):
    """
    规划路线
    
    Args:
        request: 路线规划请求
        
    Returns:
        路线信息
    """
    try:
        dbg("收到前端 /map/route 输入", request.model_dump())
        settings = get_settings()
        service = get_mapbox_service() if (settings.map_provider or "amap").lower() == "mapbox" else get_amap_service()
        dbg("传入 map service.plan_route 的参数", request.model_dump())
        
        # 规划路线
        route_info = service.plan_route(
            origin_address=request.origin_address,
            destination_address=request.destination_address,
            origin_city=request.origin_city,
            destination_city=request.destination_city,
            route_type=request.route_type
        )
        dbg("map service.plan_route 返回(概要)", {"keys": list(route_info.keys()) if isinstance(route_info, dict) else str(type(route_info))})
        
        return RouteResponse(
            success=True,
            message="路线规划成功",
            data=route_info.get("route") if isinstance(route_info, dict) else route_info
        )
        
    except Exception as e:
        print(f"❌ 路线规划失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"路线规划失败: {str(e)}"
        )


@router.get(
    "/health",
    summary="健康检查",
    description="检查地图服务是否正常"
)
async def health_check():
    """健康检查"""
    try:
        # 检查服务是否可用
        service = get_amap_service()
        
        return {
            "status": "healthy",
            "service": "map-service",
            "mcp_tools_count": len(service.mcp_tool._available_tools)
        }
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"服务不可用: {str(e)}"
        )

