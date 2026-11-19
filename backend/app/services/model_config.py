"""按用途选择 LLM 模型：站长可在页面上改，保存到 storage/model_config.json，立即生效（无需重启）。

优先级：站长在页面里的设置 > 环境变量（EZTRIP_STORY_MODEL 等）> 全局默认内容模型。
模型名必须是 LiteLLM 网关里已有的名字；这里不做价格判断，由站长自己选。
"""

from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..config import get_settings
from .llm_service import get_llm_router

ROLES: List[Dict[str, str]] = [
    {"id": "story", "label": "旅程故事旁白", "env": "EZTRIP_STORY_MODEL", "hint": "决定文案的文笔：每次生成会读整趟行程并写逐站旁白，表达力强的模型更好"},
    {"id": "place_chat", "label": "地点 AI 对话", "env": "EZTRIP_CHAT_MODEL", "hint": "详情页里的问答，要求快、便宜，流式输出。问到近期活动 / 演出 / 展览时会改用「找点乐子对话」的模型（需支持工具调用）去检索实时信息"},
    {"id": "fun_chat", "label": "找点乐子对话", "env": "EZTRIP_FUN_MODEL", "hint": "「找点乐子」多轮对话，需要支持工具调用（function calling），会调用附近地点与实时活动检索；默认 travel-tool（≈ ocx-fast）"},
    {"id": "review", "label": "行程审核", "env": "EZTRIP_REVIEW_MODEL", "hint": "多天行程生成后的独立审核（路线、节奏、时间、餐饮、重复），默认 combo/main，要求推理稳、遵循 JSON"},
    {"id": "route_advice", "label": "路线对比建议", "env": "EZTRIP_ROUTE_MODEL", "hint": "城际交通方案对比后的两三句取舍说明（价格与月票判定由程序算好，模型只负责解释），默认 travel-fast，要求快"},
    {"id": "itinerary_edit", "label": "行程 AI 优化与住宿推荐", "env": "EZTRIP_EDIT_MODEL", "hint": "整趟/单日/单卡片的修改提案与住宿片区推荐，要求遵循 JSON 格式"},
    {"id": "discover", "label": "目的地主题识别", "env": "EZTRIP_DISCOVER_MODEL", "hint": "生成前的主题引导：识别目的地的 1-3 个主题标签与规模（购物 / 历史 / 美食…），输出很短，默认 travel-fast，要求快、遵循 JSON"},
]
_IDS = {r["id"] for r in ROLES}
_NAME = re.compile(r"^[\w.\-:/@+]{1,100}$")
_lock = threading.Lock()
_cache: Dict[str, Any] = {"mtime": -1.0, "data": {}}


def _path() -> Path:
    return Path(os.getenv("EZTRIP_MODEL_CONFIG", "")) if os.getenv("EZTRIP_MODEL_CONFIG") else Path(__file__).resolve().parents[2] / "storage" / "model_config.json"


def _read() -> Dict[str, str]:
    p = _path()
    try:
        m = p.stat().st_mtime
    except OSError:
        return {}
    with _lock:
        if m == _cache["mtime"]:
            return dict(_cache["data"])
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            raw = {}
        data = {k: str(v) for k, v in (raw.items() if isinstance(raw, dict) else []) if k in _IDS and isinstance(v, str) and _NAME.match(v)}
        _cache.update(mtime=m, data=data)
        return dict(data)


def default_model(role: str) -> str:
    env = next((r["env"] for r in ROLES if r["id"] == role), "")
    if role == "review":
        from ..agent_config import model as _agent_model
        return os.getenv(env) or _agent_model("critic", "ocx-main")
    if role == "fun_chat":
        return os.getenv(env) or "travel-tool"
    if role == "route_advice":
        from ..agent_config import model as _agent_model
        return os.getenv(env) or _agent_model("route_advisor", "travel-fast")
    if role == "discover":
        from ..agent_config import model as _agent_model
        return os.getenv(env) or _agent_model("discover", "travel-fast")
    return (os.getenv(env) if env else "") or get_settings().llm_model_content or get_llm_router().primary_model


def get_model(role: str) -> str:
    return _read().get(role) or default_model(role)


def valid_name(name: str) -> bool:
    return bool(_NAME.match(name or ""))


def set_model(role: str, model: Optional[str]) -> None:
    if role not in _IDS:
        raise KeyError(role)
    if model is not None and not valid_name(model):
        raise ValueError("模型名不合法")
    data = _read()
    if model:
        data[role] = model
    else:
        data.pop(role, None)
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)
    with _lock:
        _cache["mtime"] = -1.0


def snapshot() -> List[Dict[str, Any]]:
    over = _read()
    return [
        {"id": r["id"], "label": r["label"], "hint": r["hint"], "default": default_model(r["id"]),
         "current": over.get(r["id"]) or default_model(r["id"]), "overridden": r["id"] in over}
        for r in ROLES
    ]
