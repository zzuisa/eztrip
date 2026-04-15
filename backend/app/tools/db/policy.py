"""DB 运行时策略（server-side skill policy）

说明：
- 默认策略以代码为单一来源（无需维护外部 JSON 文件）
- 支持通过环境变量进行轻量覆盖（可选）
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import os
from typing import List


@dataclass
class DbTrainPolicy:
    policy_name: str
    policy_version: str
    allowed_tools: List[str]
    default_tool: str
    default_limit: int
    month_ticket_only_default: bool
    ask_missing_fields: bool
    required_fields: List[str]
    clarification_examples: List[str]


@lru_cache(maxsize=1)
def get_db_train_policy() -> DbTrainPolicy:
    # ---- defaults (single source of truth) ----
    policy_name = "db-train-controlled-flow"
    policy_version = "1.0.0"
    allowed_tools = ["getPlannedTimetable", "getCurrentTimetable"]
    default_tool = "getPlannedTimetable"
    default_limit = 5
    month_ticket_only_default = True
    ask_missing_fields = True
    required_fields = ["origin", "destination", "time_mode"]
    clarification_examples = [
        "今天18点 杜塞尔多夫到杜伊斯堡",
        "现在 杜塞到杜堡",
    ]

    # ---- optional env overrides ----
    # DB_TRAIN_POLICY_VERSION=1.0.1
    policy_version = os.getenv("DB_TRAIN_POLICY_VERSION", policy_version).strip() or policy_version
    # DB_TRAIN_DEFAULT_LIMIT=5
    try:
        default_limit = int(os.getenv("DB_TRAIN_DEFAULT_LIMIT", str(default_limit)))
    except Exception:
        default_limit = 5
    default_limit = max(1, min(default_limit, 50))

    return DbTrainPolicy(
        policy_name=policy_name,
        policy_version=policy_version,
        allowed_tools=allowed_tools,
        default_tool=default_tool,
        default_limit=default_limit,
        month_ticket_only_default=month_ticket_only_default,
        ask_missing_fields=ask_missing_fields,
        required_fields=required_fields,
        clarification_examples=clarification_examples,
    )

