"""能力总线（Capability Bus）—— Agent 化的脊柱。

一次声明每个能力，多处复用：Agent 运行时（`app/agents/`）、HTTP API、将来的 MCP server。
导入本包会把 `catalog`（Places / 小红书）里的能力注册进全局 `REGISTRY`；
导入 `app.agents` 则会把子 Agent 也注册成工具（见 `app/agents/__init__.py`）。
"""

from .registry import REGISTRY, Tool, dispatch, get, register, specs, tool
from . import catalog as catalog  # noqa: F401  —— import 即注册确定性能力

__all__ = ["REGISTRY", "Tool", "catalog", "dispatch", "get", "register", "specs", "tool"]
