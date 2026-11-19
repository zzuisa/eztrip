"""对话历史：按访客身份（站长/匿名 Cookie）隔离，可查看、续聊、删除。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request, Response

from ...services.chat_store import get_chat_store
from ...services.identity import set_cookie, user_key
from ...services.travel_plan_store import get_travel_plan_store

router = APIRouter(prefix="/chat", tags=["ChatHistory"])


def _item(c: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": c["id"],
        "result_id": c["result_id"],
        "location": c.get("location") or "",
        "place": {"day": c["place_day"], "kind": c["place_kind"], "name": c["place_name"]},
        "title": c.get("title") or c["place_name"],
        "snippet": c.get("snippet", ""),
        "msg_count": c["msg_count"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
    }


@router.get("/conversations", summary="我的对话列表")
async def list_conversations(
    request: Request,
    response: Response,
    result_id: Optional[str] = Query(default=None, max_length=64),
    kind: Optional[str] = Query(default=None, pattern="^(activity|meal|fun)$"),
    name: Optional[str] = Query(default=None, max_length=120),
    limit: int = Query(default=60, ge=1, le=200),
):
    uk, new_uid = user_key(request)
    set_cookie(response, request, new_uid)
    response.headers["Cache-Control"] = "no-store"
    rows = get_chat_store().list(uk, result_id=result_id, kind=kind, name=name, limit=limit)
    items: List[Dict[str, Any]] = [_item(r) for r in rows]
    # 行程已被删除的对话仍可读，但标记出来，前端不再提供“回到行程”
    store = get_travel_plan_store()
    alive: Dict[str, bool] = {}
    for it in items:
        rid = it["result_id"]
        if rid not in alive:
            alive[rid] = True if rid == "fun" else store.get(rid) is not None
        it["result_exists"] = alive[rid]
    return {"items": items}


@router.get("/conversations/{conversation_id}", summary="对话消息")
async def get_conversation(conversation_id: str, request: Request, response: Response):
    uk, _ = user_key(request)
    store = get_chat_store()
    conv = store.get(uk, conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="对话不存在")
    response.headers["Cache-Control"] = "no-store"
    return {
        "conversation": _item(conv),
        "messages": [
            {"role": m["role"], "content": m["content"], "ts": m["ts"], "model": m.get("model"), "extra": m.get("extra")}
            for m in store.messages(uk, conversation_id)
        ],
    }


@router.delete("/conversations/{conversation_id}", summary="删除一段对话")
async def delete_conversation(conversation_id: str, request: Request):
    uk, _ = user_key(request)
    if not get_chat_store().delete(uk, conversation_id):
        raise HTTPException(status_code=404, detail="对话不存在")
    return {"ok": True}


@router.delete("/conversations", summary="清空我的全部对话")
async def clear_conversations(request: Request, confirm: bool = Query(default=False)):
    if not confirm:
        raise HTTPException(status_code=400, detail="需要 confirm=true")
    uk, _ = user_key(request)
    return {"ok": True, "deleted": get_chat_store().clear(uk)}

