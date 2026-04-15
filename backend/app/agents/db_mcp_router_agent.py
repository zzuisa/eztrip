"""DB MCP 路由 Agent：把自然语言拆成 MCP 工具与参数"""

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, Optional

from hello_agents import SimpleAgent

from ..services.llm_service import get_llm
from ..tools.db.debug import db_log, DbTimer


DB_MCP_ROUTER_SYSTEM_PROMPT = """你是 DB MCP 路由器。
用户会用中文提问，例如：查下现在杜塞到杜堡的车。

你的任务：把用户的话拆成“需要调用哪个 MCP 工具 + 该工具需要的关键参数（尤其是时间）”。

输出必须严格为 JSON（不要输出任何多余文本），格式如下：
{
  "mcp_tool": "getPlannedTimetable",
  "origin": "出发站/城市关键词",
  "destination": "目的地站/城市关键词",
  "time": {
    "mode": "now" | "scheduled",
    "date": "YYMMDD或null",
    "hour": "HH或null",
    "minute": "mm或null"
  },
  "limit": 5,
  "month_ticket_only": true
}

规则：
1) 如果用户说“现在/目前/立刻/马上”，time.mode 选 "now"；date/hour/minute 输出 null。
2) 如果用户显式说了日期与“点/小时”（例如 2026-04-02 18点），time.mode 选 "scheduled"，并提取 date/hour（分钟若没说就用 null）。
3) month_ticket_only：只要用户提到“月票/RE/RB/S/区域车”这类口径，就保持 true；否则也默认 true（本项目默认月票列车）。
4) limit：如果用户说“最近5/只要5/展示5趟”，就取对应数字；否则默认 5。
5) mcp_tool：本项目建议优先使用 getPlannedTimetable（即使 time.mode=now）。

示例：
用户："查下现在杜塞到杜堡的车"
输出：
{
  "mcp_tool":"getPlannedTimetable",
  "origin":"杜塞尔多夫",
  "destination":"杜伊斯堡",
  "time":{"mode":"now","date":null,"hour":null,"minute":null},
  "limit":5,
  "month_ticket_only":true
}
"""


@dataclass
class DbMcpPlan:
    mcp_tool: str
    origin: str
    destination: str
    time_mode: str
    date: Optional[str]
    hour: Optional[str]
    minute: Optional[str]
    limit: int
    month_ticket_only: bool

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "DbMcpPlan":
        t = d.get("time") or {}
        return DbMcpPlan(
            mcp_tool=str(d.get("mcp_tool") or "getPlannedTimetable"),
            origin=str(d.get("origin") or ""),
            destination=str(d.get("destination") or ""),
            time_mode=str(t.get("mode") or "scheduled"),
            date=t.get("date"),
            hour=t.get("hour"),
            minute=t.get("minute"),
            limit=int(d.get("limit") or 5),
            month_ticket_only=bool(d.get("month_ticket_only", True)),
        )


_agent: Optional[SimpleAgent] = None


def _get_agent() -> SimpleAgent:
    global _agent
    if _agent is None:
        _agent = SimpleAgent(name="DB-MCP-Router", llm=get_llm(), system_prompt=DB_MCP_ROUTER_SYSTEM_PROMPT)
    return _agent


def parse_nlq_to_mcp_plan(text: str, request_id: str) -> DbMcpPlan:
    timer = DbTimer(request_id)
    db_log(request_id, "router_input", text)
    agent = _get_agent()

    raw = agent.run(text)
    db_log(request_id, "router_llm_raw", raw)
    timer.mark("router_llm_done")

    # 提取 JSON（允许模型包裹在代码块中）
    if "```" in raw:
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, flags=re.S)
        if match:
            raw = match.group(1)

    db_log(request_id, "router_json_text", raw)
    data = json.loads(raw)
    db_log(request_id, "router_json_obj", data)

    return DbMcpPlan.from_dict(data)

