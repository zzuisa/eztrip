"""找点乐子·对话（SSE）：多轮、带记忆、可调用附近场所与实时本地活动检索。

事件：meta → (status | cards | sources)* → delta* → done；失败发 error 并退还额度。
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any, AsyncIterator, Dict, List, Literal, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ...services import fun_chat as fc
from ...services.chat_store import get_chat_store
from ...services.guest_guard import client_ip, get_quota, is_owner, limits as guest_limits
from ...services.identity import set_cookie, user_key
from ...services.model_config import get_model
from ...services import voice

router = APIRouter(prefix="/fun", tags=["FunChat"])

MAX_HISTORY = 8
MAX_MSG_CHARS = 600
FUN_RESULT_ID = "fun"
GLOBAL_KEY_IP = "all"


class FunMsg(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class FunChatRequest(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    label: str = Field(default="", max_length=80)
    messages: List[FunMsg] = Field(min_length=1, max_length=40)
    conversation_id: Optional[str] = Field(default=None, max_length=64)


def fun_model() -> str:
    return get_model("fun_chat")


def _sse(event: str, data: Dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _history_content(m: Dict[str, Any]) -> str:
    """把当时展示过的地点名带进历史，便于“第二家有包间吗”这类追问。"""
    text = str(m.get("content") or "")[:MAX_MSG_CHARS]
    extra = m.get("extra") or {}
    names = [str(c.get("name")) for c in (extra.get("cards") or []) if isinstance(c, dict) and c.get("name")]
    if m.get("role") == "assistant" and names:
        text += "\n[当时展示给用户的地点：" + "、".join(names[:8]) + "]"
    return text


def _slim_card(c: Dict[str, Any]) -> Dict[str, Any]:
    keys = ("id", "name", "lat", "lng", "address", "rating", "rating_count", "price_level", "open_now", "maps_url",
            "type_label", "photo_ref", "distance_m", "walk_min")
    return {k: c.get(k) for k in keys}


@router.post("/chat", summary="找点乐子 对话（SSE 流式，多轮 + 记忆 + 工具）")
async def fun_chat(req: FunChatRequest, request: Request):
    if req.messages[-1].role != "user":
        raise HTTPException(status_code=400, detail="最后一条消息必须来自用户")
    ip = client_ip(request)
    owner = is_owner(request)
    uk, new_uid = user_key(request)
    store = get_chat_store()
    question = req.messages[-1].content[:MAX_MSG_CHARS * 2]
    label = " ".join(req.label.split())

    conv = store.get(uk, req.conversation_id) if req.conversation_id else None
    if req.conversation_id and (not conv or conv["place_kind"] != "fun"):
        raise HTTPException(status_code=404, detail="对话不存在")

    quota, lim = get_quota(), guest_limits()
    taken_user = taken_global = False
    if not owner:
        quota.consume("funchat", ip, lim["funchat"])
        taken_user = True
        try:
            quota.consume("funchat_all", GLOBAL_KEY_IP, lim["funchat_all"])
            taken_global = True
        except HTTPException:
            quota.refund("funchat", ip)
            raise

    if conv:
        cid = conv["id"]
        stored = store.messages(uk, cid, limit=MAX_HISTORY)
        history = [{"role": m["role"], "content": _history_content(m)} for m in stored]
    else:
        cid = store.create(uk, FUN_RESULT_ID, 0, "fun", label or "找点乐子", label)
        history = [{"role": m.role, "content": m.content[:MAX_MSG_CHARS]} for m in req.messages[:-1][-(MAX_HISTORY - 1):]]
    history.append({"role": "user", "content": question})
    history = history[-MAX_HISTORY:]
    if history and history[0]["role"] != "user":
        history = history[1:] or history

    memory = ""
    try:
        recent = store.recent_user_questions(uk, FUN_RESULT_ID, cid, limit=5)
        if recent:
            memory = "【用户此前在「找点乐子」问过（体现偏好，供参考，不要逐条复述）】\n" + "\n".join(f"- {r['q'][:70]}" for r in reversed(recent))
    except Exception:  # noqa: BLE001
        pass

    model = fun_model()
    messages: List[Dict[str, Any]] = [{"role": "system", "content": fc.build_system(label, req.lat, req.lng, memory)}, *history]
    store.add_message(uk, cid, "user", question)
    runner = fc.ToolRunner(req.lat, req.lng, owner, ip)
    if conv:  # 续聊：此前搜索过的链接仍可核实
        for m in stored:
            for src in ((m.get("extra") or {}).get("sources") or []):
                if isinstance(src, dict) and src.get("url"):
                    runner.seen.add(fc._norm_url(src["url"]))

    async def gen() -> AsyncIterator[str]:
        cards: List[Dict[str, Any]] = []
        sources: List[Dict[str, Any]] = []
        text = ""
        failed = False
        try:
            yield _sse("meta", {"model": model, "conversation_id": cid, "search": fc.mcp_available()})
            async for kind, payload in fc.run_turn(messages, runner, model):
                if kind == "status":
                    yield _sse("status", payload)
                elif kind == "cards":
                    new = [_slim_card(c) for c in payload]
                    cards.extend(new)
                    yield _sse("cards", {"items": new})
                elif kind == "sources":
                    sources.extend(payload)
                    yield _sse("sources", {"items": payload})
                elif kind == "text":
                    text = payload
            text = voice.scrub_text(text)
            if not text:
                raise RuntimeError("empty answer")
            for i in range(0, len(text), 14):
                yield _sse("delta", {"text": text[i:i + 14]})
                await asyncio.sleep(0.012)
            yield _sse("done", {"ok": True, "conversation_id": cid})
        except Exception as e:  # noqa: BLE001
            failed = True
            print(f"[fun-chat] error {type(e).__name__}: {e}")
            yield _sse("error", {"message": "暂时无法回答，请稍后重试"})
        finally:
            if failed or not text:
                if taken_user:
                    quota.refund("funchat", ip)
                if taken_global:
                    quota.refund("funchat_all", GLOBAL_KEY_IP)
                store.drop_last_user(uk, cid)
            else:
                extra: Dict[str, Any] = {}
                if cards:
                    extra["cards"] = cards[: fc.MAX_CARDS * 2]
                if sources:
                    extra["sources"] = sources[:8]
                store.add_message(uk, cid, "assistant", text, model, extra or None)

    resp = StreamingResponse(
        gen(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )
    set_cookie(resp, request, new_uid)
    return resp
