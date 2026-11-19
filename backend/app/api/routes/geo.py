"""地理编码接口：定位反查 / 地址联想（供“出发地”输入与“找点乐子”使用）。"""

from __future__ import annotations

import asyncio
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException, Query, Request

from ...services import discover as discover_service, geo_service, scope as scope_service
from ...services.guest_guard import client_ip, get_quota, is_owner, limits as guest_limits
from ...services.llm_service import get_llm_router
from ...services.model_config import get_model

router = APIRouter(prefix="/geo", tags=["Geo"])

_disc_sem = asyncio.Semaphore(3)


async def _discover_complete(messages) -> str:
    r = get_llm_router()
    if not r.api_key:
        raise RuntimeError("LLM 未配置")
    body = {"model": get_model("discover"), "messages": messages, "temperature": 0.1, "max_tokens": 400, **r._extra()}
    async with httpx.AsyncClient(timeout=httpx.Timeout(connect=6.0, read=20.0, write=8.0, pool=6.0)) as c:
        resp = await c.post(f"{r.base_url}/chat/completions", headers={"Authorization": f"Bearer {r.api_key}", "Content-Type": "application/json"}, json=body)
    if resp.status_code >= 400:
        raise RuntimeError(f"upstream {resp.status_code}")
    return (((resp.json().get("choices") or [{}])[0]).get("message") or {}).get("content") or ""


@router.get("/discover", summary="生成前的主题引导：识别目的地主题标签 + 系统推荐玩法")
async def discover(
    request: Request,
    q: str = Query(..., min_length=1, max_length=60),
    days: int = Query(1, ge=1, le=15),
    prefs: str = Query("", max_length=80, description="用户已勾选的偏好，逗号分隔（只用于排序）"),
):
    """永不报错：内置表 / 缓存 → 网页摘要 + 小模型 → 通用兜底。只有“未知目的地且没缓存”才占用游客额度。"""
    loc = q.strip()
    plist = [x.strip() for x in prefs.split(",") if x.strip()][:6]
    hit = discover_service.known_tags(loc)
    if hit:
        return {"success": True, "data": discover_service.build(loc, days, hit["size"], hit["tags"], plist, "known")}
    hit = discover_service.cache_get(loc)
    if hit and hit["tags"]:
        return {"success": True, "data": discover_service.build(loc, days, hit["size"], hit["tags"], plist, "cache")}

    owner, ip, lim, quota = is_owner(request), client_ip(request), guest_limits(), get_quota()
    took_user = took_all = False
    allowed = True
    if not owner:
        try:
            quota.consume("disc", ip, lim["disc"])
            took_user = True
            quota.consume("disc_all", "all", lim["disc_all"])
            took_all = True
        except HTTPException:
            if took_user:
                quota.refund("disc", ip)
            took_user = False
            allowed = False  # 额度用完：直接给通用标签，不报错
    found = None
    if allowed:
        try:
            async with _disc_sem:
                ctx = ""
                try:
                    ctx = await asyncio.wait_for(asyncio.to_thread(discover_service.web_context, loc), timeout=8.0)
                except Exception:  # noqa: BLE001
                    ctx = ""
                found = await asyncio.wait_for(discover_service.identify(loc, _discover_complete, ctx), timeout=28.0)
        except Exception as e:  # noqa: BLE001
            print(f"[discover] failed {type(e).__name__}")
            found = None
        if found is None and not owner:  # 没产出就退还额度
            if took_user:
                quota.refund("disc", ip)
            if took_all:
                quota.refund("disc_all", "all")
    if found:
        discover_service.cache_put(loc, found["size"], found["tags"])
        return {"success": True, "data": discover_service.build(loc, days, found["size"], found["tags"], plist, "model")}
    return {"success": True, "data": discover_service.build(loc, days, "medium", discover_service.fallback_tags(plist), plist, "fallback")}



def _quota(request: Request) -> None:
    if not is_owner(request):
        get_quota().consume("geo", client_ip(request), guest_limits()["geo"])


@router.get("/reverse", summary="坐标 → 地址（出发地默认当前位置）")
async def reverse(request: Request, lat: float = Query(..., ge=-90, le=90), lng: float = Query(..., ge=-180, le=180), area: bool = False):
    _quota(request)
    try:
        res = await asyncio.to_thread(geo_service.reverse_area if area else geo_service.reverse, lat, lng)
    except Exception as e:  # noqa: BLE001
        print(f"[geo] reverse failed {type(e).__name__}")
        raise HTTPException(status_code=502, detail="暂时无法解析当前位置")
    return {"success": True, "data": res}


@router.get("/search", summary="地址联想")
async def search(
    request: Request,
    q: str = Query(..., min_length=2, max_length=80),
    lat: Optional[float] = Query(None, ge=-90, le=90),
    lng: Optional[float] = Query(None, ge=-180, le=180),
    poi: bool = False,
):
    _quota(request)
    try:
        res = await asyncio.to_thread(geo_service.search_tourism if poi else geo_service.search, q, lat, lng)
    except Exception as e:  # noqa: BLE001
        print(f"[geo] search failed {type(e).__name__}")
        raise HTTPException(status_code=502, detail="地址搜索暂时不可用")
    return {"success": True, "items": res}


@router.get('/rental-references', summary='租车平台公开地区起价参考（非实时库存报价）')
async def rental_references():
    from ...services.journey import RENTAL_REFERENCES
    return {'items': [{'provider': key, **value, 'confidence': 'reference', 'reference_date': '2026-11-10'} for key, value in RENTAL_REFERENCES.items()]}

@router.get("/scope", summary="目的地范围评估：太宽泛/不明确时返回二次提问")
async def scope(
    request: Request,
    q: str = Query(..., min_length=1, max_length=60),
    days: int = Query(3, ge=1, le=15),
):
    res = scope_service.assess(q, days)
    if res["level"] == "ok":
        # 静态规则看不出问题时，用地理编码兜底：识别“没找到 / 其实是整个国家”
        try:
            _quota(request)
            items = await asyncio.to_thread(geo_service.search, q)
        except HTTPException:
            items = None
        except Exception as e:  # noqa: BLE001
            print(f"[geo] scope lookup failed {type(e).__name__}")
            items = None
        if items is not None:
            if not items:
                res = {"level": "clarify", "kind": "unknown", "title": "没有找到这个地点",
                       "question": "地图上没有找到「" + q.strip()[:30] + "」。可以写得更具体一些（如加上城市或国家）；若确定无误，也可以仍然使用。",
                       "options": [], "allow_continue": True, "resolved": ""}
            elif items[0].get("type") == "country":
                res = {"level": "clarify", "kind": "country", "title": "「" + q.strip()[:30] + "」是整个国家",
                       "question": "整国范围较大，每天可能要长途移动。建议填一座具体城市；也可以仍按整个国家规划。",
                       "options": [], "allow_continue": True, "resolved": items[0].get("name") or ""}
            else:
                res["place"] = {k: items[0].get(k) for k in ("label", "name", "city", "country", "type", "lat", "lng")}
    return {"success": True, **res}

