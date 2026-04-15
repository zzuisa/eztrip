"""小红书 MCP(HTTP) 服务封装"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

import httpx

from ..config import get_settings


class XiaohongshuService:
    """调用第三方 xiaohongshu-mcp 的 HTTP 接口。"""

    def __init__(self) -> None:
        self._settings = get_settings()
        self.base_url = (self._settings.xiaohongshu_mcp_base_url or "http://127.0.0.1:18060").rstrip("/")
        self.timeout_s = max(5, int(self._settings.xiaohongshu_mcp_timeout_seconds or 30))

    def _dbg(self, title: str, payload: Any) -> None:
        if getattr(self._settings, "debug_xiaohongshu", False):
            text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False, indent=2)
            print(f"🧧 [小红书调试] {title}\n{text}\n")

    def _post(self, path: str, body: Dict[str, Any]) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        self._dbg(f"POST {path} 请求", body)
        with httpx.Client(timeout=self.timeout_s) as c:
            resp = c.post(url, json=body)
            resp.raise_for_status()
            data = resp.json()
        self._dbg(f"POST {path} 响应", data)
        return data

    def search_feeds(self, keyword: str, filters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        body: Dict[str, Any] = {"keyword": keyword}
        if filters:
            body["filters"] = filters
        return self._post("/api/v1/feeds/search", body)

    def get_feed_detail(
        self,
        feed_id: str,
        xsec_token: str,
        *,
        load_all_comments: bool = False,
        limit: int = 20,
        click_more_replies: bool = False,
        reply_limit: int = 10,
        scroll_speed: str = "normal",
    ) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "feed_id": feed_id,
            "xsec_token": xsec_token,
            "load_all_comments": bool(load_all_comments),
            "comment_config": {
                "click_more_replies": bool(click_more_replies),
                "max_replies_threshold": max(0, int(reply_limit)),
                "max_comment_items": max(0, int(limit)),
                "scroll_speed": scroll_speed if scroll_speed in ("slow", "normal", "fast") else "normal",
            },
        }
        return self._post("/api/v1/feeds/detail", body)


_xiaohongshu_service: Optional[XiaohongshuService] = None


def get_xiaohongshu_service() -> XiaohongshuService:
    global _xiaohongshu_service
    if _xiaohongshu_service is None:
        _xiaohongshu_service = XiaohongshuService()
    return _xiaohongshu_service
