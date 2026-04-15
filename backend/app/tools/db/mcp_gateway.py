"""DB MCP 调用层：只负责连接、列工具、调用工具（不做业务解析）"""

import asyncio
import concurrent.futures
from concurrent.futures import TimeoutError as FutureTimeoutError
from typing import Any, Dict, List

from hello_agents.protocols.mcp.client import MCPClient

from ...config import get_settings
from .debug import db_log, DbTimer


class DbMcpGateway:
    def __init__(self):
        settings = get_settings()
        self.sse_url = self._normalize_mcp_url(settings.db_mcp_sse_url)
        self._active_transport = "sse"
        self._mcp_timeout_seconds = 5

    def _normalize_mcp_url(self, url: str) -> str:
        """
        mcp.roguelife.de 的 SSE 端点是 /sse；如果用户只填了根域名，这里自动补齐。
        """
        u = (url or "").strip()
        if not u:
            return u
        if u.endswith("/"):
            u = u[:-1]
        if u.lower().endswith("/sse"):
            return u
        return f"{u}/sse"

    def _run_async(self, coro):
        """在新线程里执行协程，避免与FastAPI事件循环冲突"""

        def run_in_thread():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(coro)
            finally:
                loop.close()

        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        future = executor.submit(run_in_thread)
        try:
            return future.result(timeout=self._mcp_timeout_seconds)
        except FutureTimeoutError as e:
            future.cancel()
            executor.shutdown(wait=False, cancel_futures=True)
            raise RuntimeError("MCP调用超时") from e
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    def list_tool_names(self) -> List[str]:
        request_id = "mcp-tools"
        timer = DbTimer(request_id)

        async def _run():
            async with MCPClient(self.sse_url, transport_type=self._active_transport) as client:
                tools = await client.list_tools()
                names: List[str] = []
                for tool in tools if isinstance(tools, list) else []:
                    if isinstance(tool, dict) and isinstance(tool.get("name"), str):
                        names.append(tool["name"])
                return names

        try:
            db_log(request_id, "mcp_url", {"url": self.sse_url, "transport": self._active_transport})
            names = self._run_async(_run())
            timer.mark("mcp_list_tools_done")
            db_log(request_id, "mcp_tool_names", names)
            return names
        except Exception:
            return []

    def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        request_id = f"mcp-call-{tool_name}"
        timer = DbTimer(request_id)
        db_log(request_id, "mcp_call", {"url": self.sse_url, "tool": tool_name, "args": arguments})

        async def _run():
            async with MCPClient(self.sse_url, transport_type=self._active_transport) as client:
                return await client.call_tool(tool_name, arguments)

        result = self._run_async(_run())
        timer.mark("mcp_call_done")
        db_log(request_id, "mcp_result_raw", result)
        return result

