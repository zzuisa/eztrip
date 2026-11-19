"""能力注册表（Capability Registry）—— Agent 化的脊柱。

一次声明每个能力（name/schema/handler/risk/domain），多处复用：
Agent 运行时（`app/agents/`）、现有 HTTP API、以及将来的 MCP server。

设计要点（移植自 StockPilot `app/tools/registry.py`）：
- 框架无关：只依赖标准库。`params_schema` 用 JSON Schema，OpenAI function-calling 与 MCP 都能直接消费。
- `dispatch()` 统一入口：**sync handler 丢线程池**（eztrip 的 Places/小红书 service 都是同步阻塞的，
  这一步顺带把它们移出事件循环）、async handler 直接 await。
- **异常收敛成 `{"error": ...}`**：工具级容错是刻意的——Agent 循环不会因单个工具炸掉。
- eztrip 目前全是只读能力（无下单/写库），`risk` 仅用 `"read"`，字段保留以备将来。
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from dataclasses import dataclass
from typing import Any, Callable, Literal

log = logging.getLogger(__name__)

Risk = Literal["read", "write"]


@dataclass
class Tool:
    name: str
    description: str
    params_schema: dict                 # JSON Schema（type=object）
    handler: Callable[..., Any]         # 以 handler(**args) 调用；可 sync 或 async
    risk: Risk = "read"
    domain: str = "general"             # 供 supervisor 按领域分组（poi/food/inspiration/...）

    def openai_spec(self) -> dict:
        """OpenAI / Qwen function-calling 工具规格。"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.params_schema,
            },
        }


REGISTRY: dict[str, Tool] = {}


def register(t: Tool) -> Tool:
    if t.name in REGISTRY:
        raise ValueError(f"duplicate tool name: {t.name}")
    REGISTRY[t.name] = t
    return t


def tool(name: str, description: str, params_schema: dict, *,
         risk: Risk = "read", domain: str = "general") -> Callable:
    """装饰器：把一个函数登记为工具。函数签名即 handler。"""
    def deco(fn: Callable) -> Callable:
        register(Tool(name, description, params_schema, fn, risk, domain))
        return fn
    return deco


def get(name: str) -> Tool | None:
    return REGISTRY.get(name)


async def dispatch(name: str, args: dict | None = None) -> Any:
    """统一调用入口。未知工具 / 异常都收敛为 {"error": ...}，绝不抛给 Agent 循环。"""
    args = args or {}
    t = REGISTRY.get(name)
    if not t:
        return {"error": f"unknown tool: {name}"}
    try:
        if inspect.iscoroutinefunction(t.handler):
            return await t.handler(**args)
        return await asyncio.to_thread(lambda: t.handler(**args))
    except Exception as e:                # noqa: BLE001 —— 工具级容错是刻意的
        log.warning("tool %s(%s) failed: %s", name, args, e)
        return {"error": f"{type(e).__name__}: {e}"}


def specs(risk: set[str] | None = None, domain: str | None = None) -> list[dict]:
    """导出工具规格（OpenAI 格式）。可按 risk / domain 过滤。"""
    out = []
    for t in REGISTRY.values():
        if risk is not None and t.risk not in risk:
            continue
        if domain is not None and t.domain != domain:
            continue
        out.append(t.openai_spec())
    return out
