"""小红书 MCP 代理接口"""

from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ...config import get_settings
from ...services.xiaohongshu_service import get_xiaohongshu_service

router = APIRouter(prefix="/xhs", tags=["小红书"])


class XhsSearchFilters(BaseModel):
    """小红书搜索筛选项"""

    sort_by: str = Field("综合", description="排序依据", examples=["综合", "最新", "最多点赞", "最多评论", "最多收藏"])
    note_type: str = Field("不限", description="笔记类型", examples=["不限", "视频", "图文"])
    publish_time: str = Field("不限", description="发布时间", examples=["不限", "一天内", "一周内", "半年内"])
    search_scope: str = Field("不限", description="搜索范围", examples=["不限", "已看过", "未看过", "已关注"])
    location: str = Field("不限", description="位置距离", examples=["不限", "同城", "附近"])


class XhsSearchRequest(BaseModel):
    """小红书搜索请求"""

    keyword: str = Field(..., description="搜索关键词", examples=["上海 景点", "成都 美食 打卡"])
    filters: Optional[XhsSearchFilters] = Field(default=None, description="筛选条件")


class XhsFeedDetailRequest(BaseModel):
    """小红书帖子详情请求"""

    feed_id: str = Field(..., description="帖子 ID")
    xsec_token: str = Field(..., description="安全令牌")
    load_all_comments: bool = Field(False, description="是否加载全部评论")
    limit: int = Field(20, ge=1, le=200, description="一级评论数量，仅在 load_all_comments=true 时生效")
    click_more_replies: bool = Field(False, description="是否展开二级回复，仅在 load_all_comments=true 时生效")
    reply_limit: int = Field(10, ge=0, le=200, description="跳过回复数过多的评论阈值")
    scroll_speed: str = Field("normal", description="滚动速度", examples=["slow", "normal", "fast"])


@router.post(
    "/search",
    summary="搜索小红书内容",
    description="代理调用第三方 xiaohongshu-mcp 的 search_feeds 能力。",
    responses={
        200: {
            "description": "搜索成功",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "data": {"feeds": [], "count": 0},
                        "message": "搜索Feeds成功",
                    }
                }
            },
        },
        400: {"description": "小红书 MCP 未启用"},
        500: {"description": "搜索失败"},
    },
)
async def search_feeds(req: XhsSearchRequest):
    settings = get_settings()
    if not getattr(settings, "enable_xiaohongshu_mcp", False):
        raise HTTPException(status_code=400, detail="小红书 MCP 未启用，请设置 ENABLE_XIAOHONGSHU_MCP=true")

    try:
        service = get_xiaohongshu_service()
        filters = req.filters.model_dump() if req.filters else None
        result = service.search_feeds(keyword=req.keyword, filters=filters)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"搜索失败: {str(e)}")


@router.post(
    "/feed/detail",
    summary="获取小红书帖子详情",
    description="代理调用第三方 xiaohongshu-mcp 的 get_feed_detail 能力。",
    responses={
        200: {
            "description": "获取详情成功",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "data": {"feed_id": "xxx", "data": {}},
                        "message": "获取Feed详情成功",
                    }
                }
            },
        },
        400: {"description": "小红书 MCP 未启用"},
        500: {"description": "获取详情失败"},
    },
)
async def feed_detail(req: XhsFeedDetailRequest):
    settings = get_settings()
    if not getattr(settings, "enable_xiaohongshu_mcp", False):
        raise HTTPException(status_code=400, detail="小红书 MCP 未启用，请设置 ENABLE_XIAOHONGSHU_MCP=true")

    try:
        service = get_xiaohongshu_service()
        result = service.get_feed_detail(
            feed_id=req.feed_id,
            xsec_token=req.xsec_token,
            load_all_comments=req.load_all_comments,
            limit=req.limit,
            click_more_replies=req.click_more_replies,
            reply_limit=req.reply_limit,
            scroll_speed=req.scroll_speed,
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取详情失败: {str(e)}")


@router.get(
    "/health",
    summary="小红书服务健康检查",
    description="仅检查配置是否启用，并返回 MCP 基础地址。",
    responses={
        200: {
            "description": "服务信息",
            "content": {
                "application/json": {
                    "example": {
                        "enabled": True,
                        "base_url": "http://127.0.0.1:18060",
                    }
                }
            },
        }
    },
)
async def xhs_health():
    settings = get_settings()
    return {
        "enabled": bool(getattr(settings, "enable_xiaohongshu_mcp", False)),
        "base_url": getattr(settings, "xiaohongshu_mcp_base_url", ""),
    }
