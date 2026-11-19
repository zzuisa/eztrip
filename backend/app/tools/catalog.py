"""能力目录：把 eztrip 现有 service 注册进能力总线（复用，不重写）。

- Google Places（景点/就近餐饮）：`GooglePlacesService`（含 7 天磁盘缓存、归一化）。
- 小红书（灵感源）：`XiaohongshuService`（HTTP 代理上游 xiaohongshu-mcp）。

三个 service 方法都是**同步阻塞**的——`registry.dispatch()` 会自动丢线程池，
所以这里不必再包 `to_thread`。

小红书能力**必须可降级**：总开关关闭 / 服务不可用 / 未登录 → 返回 `{"available": False, ...}`
而不是抛错，规划流程照常进行（spec 005 FR-007）。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from ..config import get_settings
from ..services.google_places_service import get_google_places_service
from ..services.xiaohongshu_service import get_xiaohongshu_service
from .registry import REGISTRY, Tool, register

log = logging.getLogger(__name__)


# ── Google Places ────────────────────────────────────────────────────────────

def _search_places(query: str, limit: int = 10) -> List[Dict[str, Any]]:
    return get_google_places_service().search_places(str(query), limit=int(limit))


def _search_places_near_anchor(
    query: str,
    anchor_lat: float,
    anchor_lng: float,
    limit: int = 5,
    radius_meters: int = 2500,
) -> List[Dict[str, Any]]:
    return get_google_places_service().search_places_near_anchor(
        str(query),
        anchor_lat=float(anchor_lat),
        anchor_lng=float(anchor_lng),
        limit=int(limit),
        radius_meters=int(radius_meters),
    )


# ── 小红书（灵感源，可降级）──────────────────────────────────────────────────

def _xhs_enabled() -> bool:
    return bool(getattr(get_settings(), "enable_xiaohongshu_mcp", False))


def _xhs_search_feeds(keyword: str, filters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if not _xhs_enabled():
        return {"available": False, "reason": "ENABLE_XIAOHONGSHU_MCP=false", "feeds": []}
    try:
        data = get_xiaohongshu_service().search_feeds(str(keyword), filters)
    except Exception as e:                       # noqa: BLE001 —— 服务未部署/未登录/限流都走降级
        log.warning("xhs_search_feeds 降级: %s", e)
        return {"available": False, "code": getattr(e,"code","unavailable"), "reason": f"{type(e).__name__}: {e}", "feeds": []}
    return {"available": True, **(data if isinstance(data, dict) else {"data": data})}


def _xhs_feed_detail(feed_id: str, xsec_token: str, limit: int = 20) -> Dict[str, Any]:
    if not _xhs_enabled():
        return {"available": False, "reason": "ENABLE_XIAOHONGSHU_MCP=false"}
    try:
        data = get_xiaohongshu_service().get_feed_detail(
            str(feed_id), str(xsec_token), limit=int(limit))
    except Exception as e:                       # noqa: BLE001
        log.warning("xhs_feed_detail 降级: %s", e)
        return {"available": False, "reason": f"{type(e).__name__}: {e}"}
    return {"available": True, **(data if isinstance(data, dict) else {"data": data})}


# ── 注册 ─────────────────────────────────────────────────────────────────────

def _register_all() -> None:
    if "search_places" in REGISTRY:
        return  # 幂等：重复 import 不重复注册

    register(Tool(
        "search_places",
        "按文本查询检索真实地点（Google Places）。返回名称/经纬度/地址/评分/建议停留时长。"
        "景点候选的唯一可信数据源。",
        {"type": "object",
         "properties": {
             "query": {"type": "string", "description": "检索词，如『柏林 城市漫步 地标』"},
             "limit": {"type": "integer", "description": "返回条数上限", "default": 10}},
         "required": ["query"]},
        _search_places, risk="read", domain="poi"))

    register(Tool(
        "search_places_near_anchor",
        "在指定锚点坐标附近检索地点（Google Places），按距离排序。用于给某天的景点路线就近配餐。",
        {"type": "object",
         "properties": {
             "query": {"type": "string", "description": "检索词，如『柏林 晚餐 特色餐厅』"},
             "anchor_lat": {"type": "number", "description": "锚点纬度"},
             "anchor_lng": {"type": "number", "description": "锚点经度"},
             "limit": {"type": "integer", "default": 5},
             "radius_meters": {"type": "integer", "default": 2500}},
         "required": ["query", "anchor_lat", "anchor_lng"]},
        _search_places_near_anchor, risk="read", domain="food"))

    register(Tool(
        "xhs_search_feeds",
        "搜索小红书笔记，获取当地人推荐/网红打卡/避坑等『灵感』。"
        "注意：笔记没有可靠经纬度，**不可直接作为行程地点**，只能提供地名线索，"
        "须再经 search_places 校验拿到真实坐标。服务不可用时返回 available=false。",
        {"type": "object",
         "properties": {
             "keyword": {"type": "string", "description": "搜索词，如『柏林 citywalk 攻略』"},
             "filters": {"type": "object", "description": "可选过滤条件"}},
         "required": ["keyword"]},
        _xhs_search_feeds, risk="read", domain="inspiration"))

    register(Tool(
        "xhs_feed_detail",
        "获取某篇小红书笔记的详情与评论（需 feed_id 与 xsec_token，来自 xhs_search_feeds 结果）。",
        {"type": "object",
         "properties": {
             "feed_id": {"type": "string"},
             "xsec_token": {"type": "string"},
             "limit": {"type": "integer", "default": 20}},
         "required": ["feed_id", "xsec_token"]},
        _xhs_feed_detail, risk="read", domain="inspiration"))


_register_all()


# Shared HTTP/MCP/Agent capabilities. Device location is supplied by the client,
# never inferred from the server's LAN address.
def _weather(**kwargs):
    from ..services.weather import query_weather
    return query_weather(**kwargs)


def _location(lat=None, lng=None):
    from ..api.routes.weather import current_location
    return current_location(lat,lng)


if 'get_weather' not in REGISTRY:
    register(Tool('get_weather', '查询地点在指定日期或时间段的天气（地点当地时间），含来源和户外/citywalk建议。日期 YYYY-MM-DD，时间 HH:MM；未知天气不可编造。',
        {'type':'object','properties':{k:{'type':t} for k,t in [('location','string'),('lat','number'),('lng','number'),('start_date','string'),('end_date','string'),('start_time','string'),('end_time','string'),('preferences','string')]}}, _weather, domain='weather'))
    register(Tool('get_current_location', '读取调用方明确提供的用户坐标；未提供时要求浏览器授权或手动选址。不能定位远程设备，禁止猜测或使用服务器IP。',
        {'type':'object','properties':{'lat':{'type':'number'},'lng':{'type':'number'}}}, _location, domain='geo'))
