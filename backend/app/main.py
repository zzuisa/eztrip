"""
amap-mcp-server 诊断脚本

用于：
1) 检查 `uvx amap-mcp-server` 是否能正常启动
2) 列出 MCP server 当前暴露出来的 tools（以 MCPTool._available_tools 为准）
3) 可选：执行一个 smoke-test 工具调用验证链路是否通
"""

from __future__ import annotations

import argparse
import sys
import os
from typing import Any, Dict, List, Optional

# Ensure UTF-8 output on Windows so hello_agents debug logs (emoji) won't crash.
# This should run before any MCPTool initialization.
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from hello_agents.tools import MCPTool

try:
    # 作为包运行：python -m app.main
    from .config import get_settings
except ImportError:  # pragma: no cover
    # 作为脚本运行：python app/main.py（工作目录在 backend/app 之下时常见）
    from config import get_settings

_amap_mcp_tool: Optional[MCPTool] = None


def get_amap_mcp_tool() -> MCPTool:
    """获取高德地图 MCP 工具实例（单例）"""
    global _amap_mcp_tool

    if _amap_mcp_tool is not None:
        return _amap_mcp_tool

    settings = get_settings()
    if not settings.amap_api_key:
        raise ValueError("高德地图 API Key未配置：请在 .env 中设置 AMAP_API_KEY")

    try:
        # 将密钥放到当前进程环境变量里，避免 hello_agents 在 Windows 控制台编码下
        # 对传入 env={...} 的调试打印触发 UnicodeEncodeError。
        os.environ["AMAP_MAPS_API_KEY"] = settings.amap_api_key
        _amap_mcp_tool = MCPTool(
            name="amap",
            description="高德地图服务（POI搜索、路线规划、天气查询等）",
            server_command=["uvx", "amap-mcp-server"],
            env={"AMAP_MAPS_API_KEY": settings.amap_api_key},
            auto_expand=True,  # 自动展开为独立工具
        )
        return _amap_mcp_tool
    except Exception as e:
        # 这里通常能捕获：uvx 不存在、amap-mcp-server 启动失败、网络/安装失败等
        raise RuntimeError(
            "amap-mcp-server 初始化失败：请确认已安装/可由 uvx 启动，并检查 AMAP_MAPS_API_KEY 配置。"
        ) from e


def _extract_tool_name(tool: Any) -> Optional[str]:
    """从 MCPTool 暴露的数据结构里尽可能提取 tool 名称。"""
    if isinstance(tool, str):
        return tool
    if isinstance(tool, dict):
        # 常见字段：name
        name = tool.get("name")
        if isinstance(name, str) and name.strip():
            return name
        # 兜底：可能是 tool_name
        tool_name = tool.get("tool_name")
        if isinstance(tool_name, str) and tool_name.strip():
            return tool_name
    return None


def list_available_tools(mcp_tool: MCPTool) -> List[str]:
    """
    列出当前 MCP server 可用 tools。

    注意：这里依赖 `MCPTool._available_tools`（内部字段）。如果 SDK 有变更，需要同步适配。
    """
    tools = getattr(mcp_tool, "_available_tools", None) or []
    names: List[str] = []
    for tool in tools:
        n = _extract_tool_name(tool)
        if n:
            names.append(n)
    return sorted(set(names))


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Diagnose amap-mcp-server and list tools.")
    parser.add_argument("--list-tools", action="store_true", help="只列出可用 tools")
    parser.add_argument("--smoke-test", action="store_true", help="调用一次 maps_text_search 做链路测试")
    parser.add_argument("--keywords", default="故宫", help="POI 搜索关键词")
    parser.add_argument("--city", default="北京", help="POI 搜索城市")
    parser.add_argument(
        "--no-citylimit",
        action="store_true",
        help="不限制城市范围（等同 citylimit=false；默认会限制，即 citylimit=true）",
    )
    args = parser.parse_args(argv)

    mcp_tool = get_amap_mcp_tool()
    tool_names = list_available_tools(mcp_tool)

    print("✅ amap-mcp-server 可用（MCPTool 初始化成功）")
    print(f"   tools 数量: {len(tool_names)}")
    if tool_names:
        print("   tools 列表：")
        for n in tool_names:
            print(f"     - {n}")

    if args.smoke_test:
        result = mcp_tool.run(
            {
                "action": "call_tool",
                "tool_name": "maps_text_search",
                "arguments": {
                    "keywords": args.keywords,
                    "city": args.city,
                    "citylimit": str((not args.no_citylimit)).lower(),
                },
            }
        )
        # 结果类型不确定；只打印前一段避免刷屏
        s = str(result)
        print("✅ smoke-test 调用成功，结果片段：")
        print(s[:500] + ("..." if len(s) > 500 else ""))

    # 默认行为：列出 tools（上面已打印）

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))


   