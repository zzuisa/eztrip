"""出发地：清洗用户输入并生成给 LLM 的提示片段。

出发地来自用户输入/定位反查，是不可信文本：去掉换行与控制字符、限制长度，并在提示里用引号包起来。
"""

from __future__ import annotations

import re
from typing import Optional

_BAD = re.compile(r"[\x00-\x1f\x7f<>{}\[\]\"\\\\\x60]+")


def clean_origin(raw: Optional[str]) -> str:
    s = _BAD.sub(" ", str(raw or ""))
    return re.sub(r"\s+", " ", s).strip()[:120]


def origin_sentence(origin: Optional[str]) -> str:
    """给流水线模式的用户提示追加一句（空出发地返回空串）。"""
    o = clean_origin(origin)
    if not o:
        return ""
    return (
        f"；旅行者的出发地是「{o}」：若与目的地同城，第 1 天首站优先选离出发地近的；若是外地，第 1 天上午视为刚抵达、安排轻松，"
        "最后一天留出返程时间，若偏好指定了最终返回点则以该点为准"
    )


def origin_block(origin: Optional[str], location: str, day: int, days: int) -> str:
    """给 Agent 模式单天编排用的提示块：只在首日与末日出现。"""
    o = clean_origin(origin)
    if not o:
        return ""
    lines = []
    if day == 1:
        lines.append(
            f"旅行者的出发地：「{o}」。若它与「{location}」属于同一城市/地区，第 1 天第一个景点请优先选离出发地较近的；"
            "若是外地，第 1 天上午视为刚抵达：第一站要轻松、靠近市中心或交通枢纽，并在首个 route_desc 里写清抵达后的衔接。"
        )
    if day == days and days > 1:
        lines.append(f"旅行者最后一天要返回最终返回点（未另指定则为「{o}」）：下午/傍晚留出返程时间，不要把最后一站排得太晚或太远。")
    return ("\n".join(lines) + "\n") if lines else ""
