"""模型设置（仅站长）：查看/修改各功能使用的 LLM 模型。

- GET /api/settings/models         各用途的当前模型、默认值，以及网关里可选的模型
- PUT /api/settings/models/{role}  设置（model 为空字符串/null 表示恢复默认）
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ...services import model_config as mc
from ...services.guest_guard import require_owner
from ...services.llm_service import get_llm_router

router = APIRouter(prefix="/settings", tags=["Settings"])

_avail: Dict[str, Any] = {"t": 0.0, "ids": []}


class ModelBody(BaseModel):
    model: Optional[str] = None


async def available_models() -> List[str]:
    """从 LiteLLM 网关读可用模型（缓存 60 秒）；读不到就返回空，前端仍可手填。"""
    if time.time() - _avail["t"] < 60:
        return list(_avail["ids"])
    r = get_llm_router()
    ids: List[str] = []
    try:
        async with httpx.AsyncClient(timeout=6.0) as c:
            resp = await c.get(f"{r.base_url}/models", headers={"Authorization": f"Bearer {r.api_key}"})
        if resp.status_code == 200:
            ids = sorted({str(m.get("id")) for m in (resp.json().get("data") or []) if isinstance(m, dict) and m.get("id")})
    except Exception as e:  # noqa: BLE001
        print(f"[settings] list models failed {type(e).__name__}")
    _avail.update(t=time.time(), ids=ids)
    return ids


@router.get("/models", summary="各功能使用的模型")
async def get_models(request: Request):
    require_owner(request)
    return {"roles": mc.snapshot(), "available": await available_models()}


@router.put("/models/{role}", summary="设置某功能使用的模型")
async def put_model(role: str, body: ModelBody, request: Request):
    require_owner(request)
    name = (body.model or "").strip() or None
    try:
        mc.set_model(role, name)
    except KeyError:
        raise HTTPException(status_code=404, detail="未知的功能")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    avail = await available_models()
    warn = bool(name and avail and name not in avail)
    return {"roles": mc.snapshot(), "warning": "网关模型列表里没有这个名字，请确认拼写" if warn else ""}
