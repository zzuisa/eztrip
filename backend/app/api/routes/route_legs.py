"""景点间真实路径（步行/驾车）。公开接口：未命中缓存的请求对游客计入 route 配额，超额降级为直线。"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Literal, Tuple

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from ...services.guest_guard import client_ip, get_quota, is_owner, limits as guest_limits
from ...services.route_service import get_route_service, pick_mode

router = APIRouter(prefix="/route", tags=["Route"])

MAX_PAIRS = 60


class LatLng(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)


class Pair(BaseModel):
    from_: LatLng = Field(alias="from")
    to: LatLng
    mode: Literal["auto", "walking", "driving", "transit"] = "auto"

    model_config = {"populate_by_name": True}


class LegsRequest(BaseModel):
    pairs: List[Pair] = Field(min_length=1, max_length=MAX_PAIRS)


@router.post("/legs", summary="相邻地点之间的真实路径")
async def route_legs(req: LegsRequest, request: Request) -> Dict[str, Any]:
    svc = get_route_service()
    owner = is_owner(request)
    ip = client_ip(request)
    quota = get_quota()
    lim = guest_limits()["route"]

    work: List[Tuple[Tuple[float, float], Tuple[float, float], str, bool]] = []
    for p in req.pairs:
        a, b = (p.from_.lat, p.from_.lng), (p.to.lat, p.to.lng)
        mode = pick_mode(a, b, p.mode)
        allow = True
        if not owner and not svc.cached(svc.key(a, b, mode)):
            try:
                quota.consume("route", ip, lim)
            except Exception:  # noqa: BLE001  超额：直线降级，不打断页面
                allow = False
        work.append((a, b, mode, allow))

    def run() -> List[Dict[str, Any]]:
        with ThreadPoolExecutor(max_workers=4) as pool:
            return list(pool.map(lambda w: svc.leg(w[0], w[1], w[2], allow_remote=w[3]), work))

    legs = await asyncio.to_thread(run)
    return {"legs": legs}

