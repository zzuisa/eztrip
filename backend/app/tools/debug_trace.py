from __future__ import annotations

import inspect
import json
from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class DebugTraceConfig:
    enabled: bool = False
    prefix: str = "🪵"


_cfg = DebugTraceConfig(enabled=False)


def set_debug_trace(enabled: bool, prefix: str = "🪵") -> None:
    global _cfg
    _cfg = DebugTraceConfig(enabled=bool(enabled), prefix=prefix)


def _caller_file_line() -> str:
    f = inspect.currentframe()
    if not f or not f.f_back or not f.f_back.f_back:
        return "<unknown>:0"
    caller = f.f_back.f_back
    return f"{caller.f_code.co_filename}:{caller.f_lineno}"


def dbg(title: str, data: Optional[Dict[str, Any]] = None) -> None:
    if not _cfg.enabled:
        return
    where = _caller_file_line()
    payload = ""
    if data:
        try:
            payload = json.dumps(data, ensure_ascii=False, default=str)
        except Exception:
            payload = str(data)
    if payload:
        print(f"{_cfg.prefix} {title} @ {where}\n{payload}\n")
    else:
        print(f"{_cfg.prefix} {title} @ {where}\n")

