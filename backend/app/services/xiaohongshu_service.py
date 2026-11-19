"""Read-only Xiaohongshu capabilities through the authenticated LiteLLM MCP gateway."""
from __future__ import annotations

import asyncio
import json
import threading
from typing import Any, Dict, Optional
from urllib.parse import urlsplit

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from ..config import get_settings

READ_TOOLS = frozenset({'check_login_status', 'search_feeds', 'get_feed_detail'})
_call_lock = threading.BoundedSemaphore(1)


class XiaohongshuError(RuntimeError):
    """Public, credential-free diagnostic suitable for graceful planning fallback."""
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def normalize_feeds(data: Dict[str, Any]) -> Dict[str, Any]:
    """Keep the upstream shape while exposing noteCard titles to the existing agent."""
    out = dict(data)
    feeds = out.get('feeds')
    if not isinstance(feeds, list):
        raise XiaohongshuError('invalid_response', '小红书搜索结果格式异常')
    normalized = []
    for feed in feeds:
        if not isinstance(feed, dict):
            continue
        card = feed.get('noteCard') or feed.get('note_card') or feed
        if not isinstance(card, dict):
            card = feed
        item = dict(feed)
        item['title'] = str(card.get('displayTitle') or card.get('display_title') or card.get('title') or feed.get('title') or '')[:300]
        item['desc'] = str(card.get('desc') or card.get('description') or feed.get('desc') or '')[:1500]
        item['feed_id'] = str(feed.get('id') or feed.get('feed_id') or '')
        item['xsec_token'] = str(feed.get('xsecToken') or feed.get('xsec_token') or '')
        # These remain clues, never geographic coordinates or verified opening hours.
        normalized.append(item)
    out.update(feeds=normalized, count=len(normalized))
    return out


class XiaohongshuService:
    def __init__(self) -> None:
        self._settings = get_settings()
        self.base_url = (self._settings.xiaohongshu_mcp_base_url or '').rstrip('/')
        self.timeout_s = max(5, min(120, int(self._settings.xiaohongshu_mcp_timeout_seconds or 90)))
        self._api_key = getattr(self._settings, 'xiaohongshu_mcp_api_key', None) or ''
        self._server = getattr(self._settings, 'xiaohongshu_mcp_server', 'xiaohongshu')

    async def _invoke(self, tool: str, args: Dict[str, Any]):
        headers = {'Authorization': 'Bearer ' + self._api_key, 'x-mcp-servers': self._server}
        # Keep open/close in one task, as required by the SDK's anyio cancel scopes.
        async with streamablehttp_client(self.base_url, headers=headers, timeout=self.timeout_s, sse_read_timeout=self.timeout_s) as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                await session.initialize()
                return await session.call_tool(self._server + '-' + tool, args)

    def _call_tool(self, tool: str, args: Dict[str, Any]) -> Dict[str, Any]:
        if tool not in READ_TOOLS:
            raise XiaohongshuError('unsupported_tool', '旅行系统仅开放小红书只读工具')
        url = urlsplit(self.base_url)
        if url.scheme not in ('http', 'https') or not url.hostname or not url.path.endswith('/mcp') or url.username or url.password:
            raise XiaohongshuError('not_configured', '小红书 MCP 网关地址未正确配置')
        if not self._api_key:
            raise XiaohongshuError('not_configured', '小红书 MCP 访问凭据未配置')
        if not _call_lock.acquire(timeout=5):
            raise XiaohongshuError('busy', '小红书正在处理其他查询，请稍后重试')
        try:
            async def run():
                return await asyncio.wait_for(self._invoke(tool, args), self.timeout_s + 5)
            result = asyncio.run(run())
        except TimeoutError:
            raise XiaohongshuError('timeout', '小红书查询超时，请稍后重试') from None
        except Exception:
            # Upstream transport errors can contain URLs/headers. Never expose them.
            raise XiaohongshuError('connection_failed', '小红书 MCP 暂时无法连接，请检查网关权限与服务状态') from None
        finally:
            _call_lock.release()
        text = '\n'.join(getattr(c, 'text', '') or '' for c in (result.content or []) if getattr(c, 'type', '') == 'text')
        if getattr(result, 'isError', False):
            if '筛选' in text and ('失败' in text or '超时' in text):
                raise XiaohongshuError('filters_unavailable', '小红书排序筛选暂不可用，可按搜索结果中的互动数优选')
            if any(s in text for s in ('SECURITY_VERIFICATION', '安全验证', '身份验证')):
                raise XiaohongshuError('verification_required', '小红书账号需要在官方页面完成人工安全验证')
            if any(s in text for s in ('LOGIN_REQUIRED', '未登录', '请先登录', '登录已失效')):
                raise XiaohongshuError('login_required', '小红书账号未登录或登录已失效，请由站长重新扫码')
            raise XiaohongshuError('upstream_error', '小红书暂时无法完成查询，请稍后重试')
        data = getattr(result, 'structuredContent', None)
        if not isinstance(data, dict):
            try:
                data = json.loads(text)
            except (ValueError, TypeError):
                data = {'text': text} if tool == 'check_login_status' else None
        if not isinstance(data, dict):
            raise XiaohongshuError('invalid_response', '小红书返回了无法识别的查询结果')
        if data.get('success') is False or data.get('error'):
            raise XiaohongshuError('upstream_error', '小红书暂时无法完成查询，请稍后重试')
        return data['data'] if data.get('success') is True and isinstance(data.get('data'), dict) else data

    def check_login_status(self) -> Dict[str, Any]:
        data = self._call_tool('check_login_status', {})
        if isinstance(data.get('is_logged_in'), bool):
            return {'is_logged_in': data['is_logged_in'], 'site': data.get('site')}
        text = data.get('text') or ''
        if '✅ 已登录' in text:
            return {'is_logged_in': True}
        if '❌ 未登录' in text:
            return {'is_logged_in': False}
        raise XiaohongshuError('login_unconfirmed', '暂时无法确认小红书登录状态')

    def search_feeds(self, keyword: str, filters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        args: Dict[str, Any] = {'keyword': str(keyword).strip()[:120]}
        if not args['keyword']:
            raise XiaohongshuError('invalid_query', '请输入小红书搜索词')
        if filters:
            args['filters'] = {k: v for k, v in filters.items() if k in ('sort_by', 'note_type', 'publish_time', 'search_scope', 'location')}
        data = normalize_feeds(self._call_tool('search_feeds', args))
        return {'success': True, 'data': data, 'provider': 'litellm/xiaohongshu'}

    def get_feed_detail(self, feed_id: str, xsec_token: str, *, load_all_comments: bool = False, limit: int = 20, click_more_replies: bool = False, reply_limit: int = 10, scroll_speed: str = 'normal') -> Dict[str, Any]:
        args = {'feed_id': feed_id, 'xsec_token': xsec_token, 'load_all_comments': bool(load_all_comments), 'limit': max(1, min(200, int(limit))), 'click_more_replies': bool(click_more_replies), 'reply_limit': max(0, min(200, int(reply_limit))), 'scroll_speed': scroll_speed if scroll_speed in ('slow', 'normal', 'fast') else 'normal'}
        return {'success': True, 'data': self._call_tool('get_feed_detail', args), 'provider': 'litellm/xiaohongshu'}


_xiaohongshu_service: Optional[XiaohongshuService] = None


def get_xiaohongshu_service() -> XiaohongshuService:
    global _xiaohongshu_service
    if _xiaohongshu_service is None:
        _xiaohongshu_service = XiaohongshuService()
    return _xiaohongshu_service
