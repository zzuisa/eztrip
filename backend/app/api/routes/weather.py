"""Shared read-only weather endpoint for browsers and the local-events MCP."""
import asyncio
from fastapi import APIRouter, Query, Request, HTTPException
from ...services import weather as service
from ...services import geo_service
from ...services.guest_guard import client_ip, get_quota, is_owner, limits

router = APIRouter(prefix='/weather', tags=['天气'])
_sem = asyncio.Semaphore(6)

@router.get('/query')
async def query(request: Request, location: str = Query('', max_length=120),
                lat: float | None = Query(None, ge=-90, le=90), lng: float | None = Query(None, ge=-180, le=180),
                start_date: str = Query('', max_length=10), end_date: str = Query('', max_length=10),
                start_time: str = Query('', max_length=5), end_time: str = Query('', max_length=5),
                preferences: str = Query('', max_length=300)):
    if not is_owner(request): get_quota().consume('geo', client_ip(request), limits()['geo'])
    try:
        async with _sem:
            report = await asyncio.to_thread(service.query_weather, location, lat, lng, start_date, end_date, start_time, end_time, preferences)
        return {'success': True, 'data': report}
    except ValueError as e:
        raise HTTPException(422, detail=str(e))


def current_location(lat=None, lng=None) -> dict:
    if lat is None or lng is None:
        return {'status': 'client_location_required', 'message': '需要用户在浏览器点击“使用当前位置”并授权，或手动选择地点；服务器和 MCP 不能定位远程设备。'}
    import math
    if not all(isinstance(v,(float,int)) and math.isfinite(v) for v in (lat,lng)) or not -90 <= lat <= 90 or not -180 <= lng <= 180:
        raise ValueError('无效的经纬度')
    try: point = geo_service.reverse(lat,lng)
    except Exception: point = None
    return {'status': 'available', 'source': 'client_provided_coordinates', 'lat': lat, 'lng': lng,
            'label': (point or {}).get('label') or '所提供坐标',
            'message': '坐标来自调用方，仅解释已提供的位置；不代表服务器获取到了设备 GPS。'}

@router.get('/location')
async def location(request: Request, lat: float | None = Query(None,ge=-90,le=90), lng: float | None = Query(None,ge=-180,le=180)):
    if not is_owner(request): get_quota().consume('geo',client_ip(request),limits()['geo'])
    return await asyncio.to_thread(current_location,lat,lng)
