"""DB MCP 调用层：常驻会话（优先经 LiteLLM MCP 网关，Streamable HTTP + Bearer 虚拟 key；也兼容直连 SSE）（后台事件循环线程）+ 自动重连。

旧实现每次调用都新建线程/事件循环/SSE 连接（约 0.3~1s 开销，且并发时连接易失败），多小时窗口查询会被放大成十几秒。
这里用一个常驻会话复用连接；会话异常时丢弃并重连一次。对外仍是同步的 call_tool / list_tool_names。
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any, Dict, List, Optional

from mcp import ClientSession
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamablehttp_client

from ...config import get_settings
from .debug import db_log

CALL_TIMEOUT = 25.0


class DbMcpGateway:
    def __init__(self, server: Optional[str] = None):
        """server=None 为 DB Timetable；传入其它 LiteLLM MCP 服务名（如 local_events）即可复用同一套常驻会话逻辑。"""
        settings = get_settings()
        self._quiet = server is not None
        raw = (settings.db_mcp_sse_url or "").strip().rstrip("/")
        # /mcp 结尾 = LiteLLM MCP 网关；其它（/sse 或裸地址）= 直连上游 SSE（回退路径）
        self.via_gateway = raw.lower().endswith("/mcp")
        self.sse_url = raw if self.via_gateway else self._normalize_mcp_url(raw)
        self._server = server or settings.db_mcp_server
        self._api_key = settings.db_mcp_api_key or settings.llm_api_key or ""
        self._tool_map: Dict[str, str] = {}  # 逻辑名 -> 网关实际名（如 db_timetable-findStations）
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._start_lock = threading.Lock()
        self._session: Optional[ClientSession] = None
        self._stop: Optional[asyncio.Event] = None
        self._conn_lock: Optional[asyncio.Lock] = None

    @staticmethod
    def _normalize_mcp_url(url: str) -> str:
        u = (url or "").strip().rstrip("/")
        if not u:
            return u
        return u if u.lower().endswith("/sse") else f"{u}/sse"

    # ---------- 后台循环 ----------
    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        with self._start_lock:
            if self._loop is None:
                loop = asyncio.new_event_loop()

                def run() -> None:
                    asyncio.set_event_loop(loop)
                    loop.run_forever()

                t = threading.Thread(target=run, name=f"mcp-loop-{self._server}", daemon=True)
                t.start()
                self._loop, self._thread = loop, t
                fut = asyncio.run_coroutine_threadsafe(self._init_lock(), loop)
                fut.result(timeout=5)
            return self._loop

    async def _init_lock(self) -> None:
        self._conn_lock = asyncio.Lock()

    async def _runner(self, ready: "asyncio.Future[ClientSession]", stop: asyncio.Event) -> None:
        # anyio 的 cancel scope 必须在“打开它的同一个 task”里关闭：整个会话生命周期放在这个 task 里
        try:
            async with self._transport() as streams:
                read, write = streams[0], streams[1]
                async with ClientSession(read, write) as session:
                    await asyncio.wait_for(session.initialize(), 10)
                    await self._load_tool_map(session)
                    self._session = session
                    if not ready.done():
                        ready.set_result(session)
                    await stop.wait()
        except BaseException as e:  # noqa: BLE001
            if not ready.done():
                ready.set_exception(e)
        finally:
            self._session = None

    def _transport(self):
        if self.via_gateway:
            headers = {"x-mcp-servers": self._server}
            if self._api_key:
                headers["Authorization"] = "Bearer " + self._api_key
            return streamablehttp_client(self.sse_url, headers=headers, timeout=6, sse_read_timeout=900)
        return sse_client(self.sse_url, timeout=6, sse_read_timeout=900)

    async def _load_tool_map(self, session: ClientSession) -> None:
        """LiteLLM 会给工具名加服务器前缀（db_timetable-findStations）；这里建立 逻辑名 -> 实际名 的映射。"""
        res = await asyncio.wait_for(session.list_tools(), 10)
        m: Dict[str, str] = {}
        for t in res.tools:
            m[t.name] = t.name
            for sep in ("-", "__", "."):
                if sep in t.name:
                    m.setdefault(t.name.split(sep, 1)[1], t.name)
        self._tool_map = m

    async def _get_session(self) -> ClientSession:
        if self._session is not None:
            return self._session
        assert self._conn_lock is not None
        async with self._conn_lock:
            if self._session is not None:
                return self._session
            loop = asyncio.get_running_loop()
            ready: asyncio.Future = loop.create_future()
            stop = asyncio.Event()
            self._stop = stop
            loop.create_task(self._runner(ready, stop))
            try:
                return await asyncio.wait_for(ready, 15)
            except BaseException:
                stop.set()
                raise

    def _reset(self) -> None:
        if self._stop is not None:
            self._stop.set()
        self._session = None

    async def _call(self, name: str, args: Optional[Dict[str, Any]]) -> Any:
        last: Optional[BaseException] = None
        for attempt in (1, 2):
            try:
                session = await self._get_session()
                if name == "__list_tools__":
                    res = await asyncio.wait_for(session.list_tools(), CALL_TIMEOUT)
                    return sorted(set(self._tool_map.values()))
                real = self._tool_map.get(name, name)
                res = await asyncio.wait_for(session.call_tool(real, args or {}), CALL_TIMEOUT)
                text = "".join(getattr(c, "text", "") or "" for c in (res.content or []))
                if getattr(res, "isError", False):
                    raise RuntimeError(f"MCP 工具 {name} 返回错误：{text[:200]}")
                return text
            except RuntimeError:
                raise
            except BaseException as e:  # noqa: BLE001  超时/连接断开：丢弃会话，重连后再试一次
                last = e
                self._reset()
                if attempt == 2:
                    break
        raise RuntimeError(f"MCP 调用失败：{type(last).__name__}: {last}") from last

    # ---------- 同步接口 ----------
    def _run(self, name: str, args: Optional[Dict[str, Any]]) -> Any:
        loop = self._ensure_loop()
        fut = asyncio.run_coroutine_threadsafe(self._call(name, args), loop)
        try:
            return fut.result(timeout=CALL_TIMEOUT * 2 + 20)
        except Exception:
            fut.cancel()
            raise

    def list_tool_names(self) -> List[str]:
        try:
            return list(self._run("__list_tools__", None))
        except Exception:  # noqa: BLE001
            return []

    def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        if not self._quiet:
            db_log(f"mcp-call-{tool_name}", "mcp_call", {"url": self.sse_url, "gateway": self.via_gateway, "tool": tool_name, "args": arguments})
        result = self._run(tool_name, arguments)
        if not self._quiet:
            db_log(f"mcp-call-{tool_name}", "mcp_result_raw", result)
        return result

