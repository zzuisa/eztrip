"""NLQ 编排（受控流程）：policy + router agent -> 标准化/校验 -> 执行参数"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Optional, Tuple
from zoneinfo import ZoneInfo

from ...models.schemas import DbTripQueryRequest
from ...agents.db_mcp_router_agent import parse_nlq_to_mcp_plan
from .debug import db_log, DbTimer
from .policy import get_db_train_policy


def _now_berlin_yyMMdd_HHmm() -> Tuple[str, str, str]:
    now = datetime.now(ZoneInfo("Europe/Berlin"))
    yy = str(now.year)[2:]
    mm = f"{now.month:02d}"
    dd = f"{now.day:02d}"
    HH = f"{now.hour:02d}"
    Min = f"{now.minute:02d}"
    date = f"{yy}{mm}{dd}"  # YYMMDD
    return date, HH, Min


def _normalize_date_yyMMdd(value: str) -> str:
    s = (value or "").strip()
    if not s:
        return s
    s = s.replace("-", "").replace("/", "").replace(".", "")
    if len(s) == 6 and s.isdigit():
        return s
    if len(s) == 8 and s.isdigit():
        return s[2:]  # YYYYMMDD -> YYMMDD
    return s


def _normalize_hour_HH(value: str) -> str:
    s = (value or "").strip()
    if not s:
        return s
    m = re.search(r"(\d{1,2})", s)
    if not m:
        return s
    hh = int(m.group(1))
    hh = max(0, min(hh, 23))
    return f"{hh:02d}"


def _build_clarification(missing_cn: list[str]) -> str:
    policy = get_db_train_policy()
    base = f"请补充{'、'.join(missing_cn)}"
    if policy.clarification_examples:
        examples = "；".join([f"'{x}'" for x in policy.clarification_examples[:2]])
        return f"{base}，例如：{examples}"
    return f"{base}，例如：'今天18点 杜塞尔多夫到杜伊斯堡'"


def parse_nlq_to_trip_query_with_time_filter(
    text: str,
) -> Tuple[DbTripQueryRequest, Optional[str], Optional[str], int, bool, Optional[str], str]:
    """
    返回：
    - DbTripQueryRequest：用于 query_trips
    - min_departure_time：YYMMDDHHmm（only now）
    - timetable_tool_override：MCP 工具名（白名单 enforced）
    - limit：top-N
    - month_ticket_only：RE/RB/S 过滤开关
    - clarification：缺参时的反问（非空则不应执行 MCP）
    - policy_version：服务端策略版本
    """
    request_id = f"nlq-{id(text)}"
    timer = DbTimer(request_id)
    db_log(request_id, "nlq_request", {"query": text})

    policy = get_db_train_policy()
    plan = parse_nlq_to_mcp_plan(text, request_id=request_id)
    timer.mark("nlq_router_done")

    requested_tool = str(getattr(plan, "mcp_tool", None) or policy.default_tool)
    allowed = {t.lower() for t in policy.allowed_tools}
    timetable_tool_override = requested_tool if requested_tool.lower() in allowed else policy.default_tool

    limit = max(1, min(int(getattr(plan, "limit", policy.default_limit) or policy.default_limit), 50))
    month_ticket_only = bool(getattr(plan, "month_ticket_only", policy.month_ticket_only_default))

    missing: list[str] = []
    if "origin" in policy.required_fields and not str(getattr(plan, "origin", "")).strip():
        missing.append("出发地")
    if "destination" in policy.required_fields and not str(getattr(plan, "destination", "")).strip():
        missing.append("目的地")
    if "time_mode" in policy.required_fields and not str(getattr(plan, "time_mode", "")).strip():
        missing.append("时间")
    if missing and policy.ask_missing_fields:
        clarification = _build_clarification(missing)
        fallback = DbTripQueryRequest(origin="", destination="", date="", hour="", language="de")
        return fallback, None, None, limit, month_ticket_only, clarification, policy.policy_version

    if plan.time_mode == "now":
        date, HH, Min = _now_berlin_yyMMdd_HHmm()
        min_departure_time = f"{date}{HH}{Min}"
        req = DbTripQueryRequest(origin=plan.origin, destination=plan.destination, date=date, hour=HH, language="de")
        return req, min_departure_time, timetable_tool_override, limit, month_ticket_only, None, policy.policy_version

    if plan.date and plan.hour:
        req = DbTripQueryRequest(
            origin=plan.origin,
            destination=plan.destination,
            date=_normalize_date_yyMMdd(str(plan.date)),
            hour=_normalize_hour_HH(str(plan.hour)),
            language="de",
        )
        return req, None, timetable_tool_override, limit, month_ticket_only, None, policy.policy_version

    clarification = _build_clarification(["时间"])
    fallback = DbTripQueryRequest(origin=str(plan.origin or ""), destination=str(plan.destination or ""), date="", hour="", language="de")
    return fallback, None, None, limit, month_ticket_only, clarification, policy.policy_version

