"""DB 调试日志工具（受 DEBUG_DB 开关控制）"""

import json
import time
from typing import Any

from ...config import get_settings


def db_debug_enabled() -> bool:
    return bool(get_settings().debug_db)


def _truncate(s: str, limit: int = 2000) -> str:
    if len(s) <= limit:
        return s
    return s[:limit] + f"...(truncated,{len(s)} chars)"


def db_log(request_id: str, stage: str, payload: Any = None):
    if not db_debug_enabled():
        return
    stage_zh = {
        "nlq_request": "收到自然语言请求",
        "nlq_input": "用户原始提问",
        "nlq_llm_raw": "LLM原始输出",
        "nlq_json_text": "从输出中提取JSON文本",
        "nlq_json_obj": "JSON解析结果(结构化参数)",
        "nlq_parsed_obj": "NLQ解析后的查询参数",
        "nlq_trips_count": "最终返回车次数量",
        "nlq_error": "发生错误",
        "mcp_url": "准备连接MCP服务",
        "mcp_tool_names": "MCP可用工具列表",
        "mcp_call": "调用MCP工具(入参)",
        "mcp_result_raw": "MCP工具返回(原始，已截断)",
        "origin_stations": "出发地站点候选(已解析)",
        "dest_stations": "目的地站点候选(已解析)",
        "chosen_stations": "选定站点(用于查询)",
        "timetable_raw": "时刻表原始返回(已截断)",
        "trips_filtered": "按目的地过滤后的车次",
    }.get(stage, "")

    prefix = f"[DEBUG_DB][{request_id}][{stage}]"
    if stage_zh:
        prefix = f"{prefix} {stage_zh}"
    if payload is None:
        print(prefix)
        return
    try:
        if isinstance(payload, (dict, list)):
            text = json.dumps(payload, ensure_ascii=False)
        else:
            text = str(payload)
        print(prefix, _truncate(text))
    except Exception as e:
        print(prefix, f"<log_error:{e}>")


class DbTimer:
    def __init__(self, request_id: str):
        self.request_id = request_id
        self._t0 = time.perf_counter()

    def mark(self, stage: str):
        if not db_debug_enabled():
            return
        dt_ms = int((time.perf_counter() - self._t0) * 1000)
        print(f"[DEBUG_DB][{self.request_id}][{stage}] +{dt_ms}ms")

