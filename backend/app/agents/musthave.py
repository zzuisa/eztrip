"""偏好“必选项”保障：用户偏好里点名了某类地点（如温泉）时，候选池里必须有，并且必须被排进某一天。

实测：偏好“温泉”，但景点检索没搜到温泉 → 三天都没有温泉，被审核判为硬伤。
做法：偏好命中规则 → 候选池里没有就单独检索一次（走 Google 缓存，最多一次调用）→ 标 must_include，
编排提示词要求必须排入，编排后代码再兜底补入。
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Callable, Dict, List

from ..services.itinerary_utils import _normalize_attractions
from ..services.pace import is_spa
from . import context as ctx_mod

log = logging.getLogger(__name__)

# (偏好正则, 检索词, 候选判定)
RULES: List[Dict[str, Any]] = [
    {"key": "spa", "prefs": re.compile(r"温泉|水疗|泡汤|spa|thermal|hot[ -]?spring|onsen|hammam", re.I),
     "query": "thermal bath spa 温泉",
     "test": lambda x: is_spa(str(x.get("name") or ""), "", str(x.get("primary_type") or ""))},
]

_EATERY_WORDS = ("restaurant", "bistro", "bistrot", "cafe", "café", "kávézó", "étterem", "vendéglő", "pizzeria", "trattoria", "brasserie", "bar &", "餐厅", "餐馆", "咖啡")


def looks_like_eatery(name: Any) -> bool:
    """旧缓存里没有 primary_type：用名字兜底识别餐厅/咖啡馆，避免它们混进景点。"""
    n = str(name or "").lower()
    return any(w in n for w in _EATERY_WORDS)


def target_day(ctx: Any) -> int:
    """必选项放在哪天：1 天放第 1 天；2 天放第 2 天；3 天以上放中间偏后的一天（头尾两天多为到达/返程）。"""
    d = max(1, int(ctx.days))
    if d <= 2:
        return d
    return min(d - 1, d // 2 + 1)


def _is_must(x: Dict[str, Any]) -> bool:
    return bool(x.get("must_include"))


def rating_of(x: Dict[str, Any]) -> float:
    try:
        return float(x.get("rating") or 0)
    except (TypeError, ValueError):
        return 0.0


async def ensure_preference_picks(ctx: Any, service: Any) -> List[str]:
    """返回被保障的地点名。出错只记录日志，不影响规划。"""
    out: List[str] = []
    if '[experience:' in str(ctx.preferences or ''):return out
    for rule in RULES:
        if not rule["prefs"].search(str(ctx.preferences or "")):
            continue
        try:
            existing = [a for a in ctx.all_attractions() if rule["test"](a)]
            if existing:
                best = max(existing, key=rating_of)
                best["must_include"] = True
                out.append(str(best.get("name") or ""))
                continue
            await ctx_mod.emit({"type": "phase", "agent": "poi_scout", "status": "running",
                                "detail": "偏好里有「%s」，补充检索" % rule["key"].replace("spa", "温泉/水疗")})
            raw = await asyncio.to_thread(service.search_places, "%s %s" % (ctx.location, rule["query"]), 10)
            cands = [x for x in _normalize_attractions(raw or []) if rule["test"](x)]
            if not cands:
                continue
            pick = max(cands, key=rating_of)
            pick["must_include"] = True
            day = target_day(ctx)
            have = {str(a.get("name") or "").strip().lower() for a in ctx.attractions_by_day.get(day, [])}
            if str(pick.get("name") or "").strip().lower() not in have:
                ctx.attractions_by_day.setdefault(day, []).insert(0, pick)
            out.append(str(pick.get("name") or ""))
        except Exception as e:                       # noqa: BLE001
            log.warning("偏好必选项检索失败（跳过）: %s", e)
    return out


def must_block(attractions: List[Dict[str, Any]]) -> str:
    must = [a for a in attractions if _is_must(a)]
    if not must:
        return ""
    names = "、".join("%s（停留不少于 %s 分钟）" % (a.get("name"), a.get("suggested_stay_minutes") or 90) for a in must)
    return "\n必须排入当天：%s——这是用户偏好点名要去的，不能省略，其余景点围绕它安排。\n" % names
