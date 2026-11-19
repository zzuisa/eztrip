"""确定性润色（不调用模型）：交给审核员之前、以及每次重排之后，先用代码修掉“一眼就错”的问题。

1. repair_times：用餐时间落在不合理窗口（16:10 的“晚餐”、10:40 的“午餐”）或与景点冲突 → 先在窗口内找空档；
   找不到就把餐插在最合适的两个景点之间，并把后面的景点顺延（当天结束不晚于 23:00 才生效，否则保持原样）。景点之间互相重叠也顺延消除。
2. dedupe_meals：同一家餐厅在多天（或同一天的多餐）重复 → 用候选池里没用过、离当天路线最近的同餐别餐厅替换。
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from ..services.day_geo import _coord, haversine_km
from ..services.itinerary_utils import _ensure_list
from ..services.pace import TIGHT, detect_pace, is_spa, max_sights, min_stay

_RANGE = re.compile(r"(\d{1,2}):(\d{2})\s*[-–~—]\s*(\d{1,2}):(\d{2})")
# 餐别 → (允许的开始时间窗口[分钟], 理想开始[分钟], 默认时长[分钟])
_WINDOW = {
    "breakfast": ((6 * 60 + 30, 10 * 60 + 30), 8 * 60, 45),
    "lunch": ((11 * 60, 14 * 60 + 30), 12 * 60 + 30, 60),
    "dinner": ((17 * 60 + 30, 21 * 60 + 30), 18 * 60 + 45, 75),
}
_ORDER = {"breakfast": 0, "lunch": 1, "dinner": 2}
_BUF = 5
_DAY_END = 23 * 60


def parse_range(text: Any) -> Optional[Tuple[int, int]]:
    m = _RANGE.search(str(text or ""))
    if not m:
        return None
    a, b = int(m.group(1)) * 60 + int(m.group(2)), int(m.group(3)) * 60 + int(m.group(4))
    if not (0 <= a < 24 * 60) or b <= a or b > 26 * 60:
        return None
    return a, b


def fmt_range(a: int, b: int) -> str:
    return "%02d:%02d-%02d:%02d" % (a // 60 % 24, a % 60, b // 60 % 24, b % 60)


def _hit(a: int, b: int, others: List[Tuple[int, int]], pad: int = 0) -> bool:
    return any(a < y + pad and x - pad < b for x, y in others)


def _meal_len(rng: Optional[Tuple[int, int]], default: int) -> int:
    if rng and rng[1] - rng[0] >= 20:
        return max(30, min(rng[1] - rng[0], 90))
    return default


def _repair_day(day: Dict[str, Any]) -> int:
    acts = [a for a in _ensure_list(day.get("activities")) if isinstance(a, dict)]
    rngs = [parse_range(a.get("time")) for a in acts]
    if not acts or any(r is None for r in rngs):
        return 0                                   # 景点没有可解析的时间：不碰这一天
    items = sorted(zip(acts, rngs), key=lambda x: x[1][0])
    cur: List[List[int]] = [list(r) for _, r in items]          # 景点的新时间（可被顺延）
    orig_act = [tuple(r) for _, r in items]
    # 1) 景点之间重叠 → 顺延
    for i in range(1, len(cur)):
        if cur[i][0] < cur[i - 1][1]:
            d = cur[i - 1][1] - cur[i][0]
            cur[i][0] += d
            cur[i][1] += d

    def shift_after(k: int, floor: int) -> None:
        """从第 k+1 个景点起顺延，使其开始时间不早于 floor。"""
        for j in range(k + 1, len(cur)):
            if cur[j][0] < floor:
                d = floor - cur[j][0]
                cur[j][0] += d
                cur[j][1] += d
            floor = cur[j][1] + _BUF

    meals = [m for m in _ensure_list(day.get("meals")) if isinstance(m, dict)]
    meals.sort(key=lambda m: _ORDER.get(str(m.get("type") or "").strip().lower(), 9))
    placed: List[Tuple[Dict[str, Any], Tuple[int, int]]] = []   # (餐, 新时间)

    def taken() -> List[Tuple[int, int]]:
        return [tuple(c) for c in cur] + [r for _, r in placed]

    for m in meals:
        slot = str(m.get("type") or "").strip().lower()
        rng = parse_range(m.get("time"))
        win = _WINDOW.get(slot)
        if not win:
            if rng:
                placed.append((m, rng))
            continue
        (lo, hi), ideal, dur = win
        L = _meal_len(rng, dur)
        if rng and lo <= rng[0] <= hi and not _hit(rng[0], rng[1], taken()):
            placed.append((m, rng))
            continue
        spot = None
        starts = sorted(range(lo, hi + 1, 15), key=lambda s: abs(s - ideal))
        for pad in (_BUF, 0):
            for s in starts:
                if not _hit(s, s + L, taken(), pad):
                    spot = (s, s + L)
                    break
            if spot:
                break
        if not spot:                                # 没有空档：插到最合适的两个景点之间，后面的顺延
            cands = sorted((abs(c[1] + _BUF - ideal), k) for k, c in enumerate(cur) if lo <= c[1] + _BUF <= hi)
            if cands:
                k = cands[0][1]
                s = cur[k][1] + _BUF
                spot = (s, s + L)
                shift_after(k, s + L + _BUF)
        if spot:
            placed.append((m, spot))
        elif rng:
            placed.append((m, rng))
    end = max([c[1] for c in cur] + [r[1] for _, r in placed] + [0])
    if end > _DAY_END:
        return 0                                    # 顺延后太晚：放弃修改，交给审核员 / 重排
    changed = 0
    for (a, _), c, o in zip(items, cur, orig_act):
        if tuple(c) != o:
            a["time"] = fmt_range(*c)
            changed += 1
    for m, r in placed:
        if r != parse_range(m.get("time")):
            m["time"] = fmt_range(*r)
            changed += 1
    return changed


def repair_times(itinerary: List[Dict[str, Any]]) -> int:
    """原地修正每天的用餐 / 景点时间，返回改动的条目数。"""
    return sum(_repair_day(d) for d in itinerary if isinstance(d, dict))


fix_meal_times = repair_times   # 旧名字


def _centroid(day: Dict[str, Any]) -> Optional[Tuple[float, float]]:
    pts = [c for c in (_coord(a) for a in _ensure_list(day.get("activities")) if isinstance(a, dict)) if c]
    if not pts:
        return None
    return sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)


def dedupe_meals(itinerary: List[Dict[str, Any]], ctx: Any) -> int:
    """原地替换重复的餐厅，返回替换数。候选来自 ctx（没有候选就保持原样）。"""
    used = set()
    for day in itinerary:                           # 景点名也算“已用”，避免餐厅与景点同名
        for a in _ensure_list(day.get("activities")) if isinstance(day, dict) else []:
            if isinstance(a, dict) and str(a.get("name") or "").strip():
                used.add(str(a["name"]).strip().lower())
    n = 0
    seen: set = set()
    for i, day in enumerate(sorted((d for d in itinerary if isinstance(d, dict)), key=lambda d: int(d.get("day") or 0))):
        dno = int(day.get("day") or i + 1)
        pool_all = list((getattr(ctx, "meals_by_day", {}) or {}).get(dno) or [])
        by_type = ((getattr(ctx, "meal_sources", {}) or {}).get(dno) or {}).get("by_type") or {}
        center = _centroid(day)
        for m in _ensure_list(day.get("meals")):
            if not isinstance(m, dict):
                continue
            key = str(m.get("name") or "").strip().lower()
            if not key:
                continue
            if key not in seen:
                seen.add(key)
                continue
            slot = str(m.get("type") or "").strip().lower()
            cands = [c for c in (_ensure_list(by_type.get(slot)) + pool_all) if isinstance(c, dict)]
            cands = [c for c in cands if str(c.get("name") or "").strip() and str(c["name"]).strip().lower() not in seen
                     and str(c["name"]).strip().lower() not in used]
            if not cands:
                continue

            def dist(c: Dict[str, Any]) -> float:
                cc = _coord(c)
                return haversine_km(center, cc) if (center and cc) else 99.0
            best = min(cands, key=dist)
            m.update({"name": str(best["name"]).strip(), "address": best.get("address") or best.get("formatted_address") or "",
                      "latitude": best.get("latitude", best.get("lat")), "longitude": best.get("longitude", best.get("lng")),
                      "place_id": best.get("place_id") or "", "estimated_cost": float(best.get("estimated_cost") or m.get("estimated_cost") or 0),
                      "description": best.get("description") or ""})
            seen.add(str(best["name"]).strip().lower())
            n += 1
    return n


_SIGHT_END = 20 * 60          # 景点最晚结束（之后留给晚餐和休息）
_GAP = 10                     # 拉长停留后与下一个景点之间至少留的分钟数


def _pool_index(ctx: Any) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    try:
        for a in ctx.all_attractions():
            if isinstance(a, dict) and str(a.get("name") or "").strip():
                out.setdefault(str(a["name"]).strip().lower(), a)
    except Exception:                                  # noqa: BLE001
        pass
    return out


def _enforce_day(day: Dict[str, Any], pool: Dict[str, Dict[str, Any]], pace: str, citywalk: bool) -> Tuple[int, int]:
    acts = [a for a in _ensure_list(day.get("activities")) if isinstance(a, dict)]
    rngs = [parse_range(a.get("time")) for a in acts]
    if not acts or any(r is None for r in rngs):
        return 0, 0
    items = sorted(zip(acts, rngs), key=lambda x: x[1][0])
    rows = []
    for a, r in items:
        src = pool.get(str(a.get("name") or "").strip().lower()) or {}
        need = min_stay(str(a.get("name") or ""), str(a.get("category") or src.get("category") or ""), str(src.get("primary_type") or ""), pace) or 0
        rows.append({"a": a, "s": r[0], "e": r[1], "need": need, "spa": is_spa(str(a.get("name") or ""), "", str(src.get("primary_type") or "")), "orig": r})

    # 一天最多一个温泉/水疗：连泡两处既累又挤（保留偏好点名的那个，否则保留最早的）
    spas = [k for k, w in enumerate(rows) if w["spa"]]
    pre_dropped = 0
    if len(spas) > 1:
        must = [k for k in spas if (pool.get(str(rows[k]["a"].get("name") or "").strip().lower()) or {}).get("must_include")]
        keep_k = must[0] if must else spas[0]
        for k in sorted((k for k in spas if k != keep_k), reverse=True):
            rows.pop(k)
            pre_dropped += 1

    def settle() -> None:
        for k, w in enumerate(rows):
            if w["e"] - w["s"] < w["need"]:
                w["e"] = w["s"] + w["need"]
            prev = rows[k - 1] if k else None
            if prev and (w["s"] < prev["e"] or (prev["e"] != prev["orig"][1] and w["s"] < prev["e"] + _GAP)):
                d = rows[k - 1]["e"] + _GAP - w["s"]
                w["s"] += d
                w["e"] += d

    cap = 5 if pace != TIGHT else 8
    if citywalk:
        cap += 1
    dropped = pre_dropped

    def drop_one() -> bool:
        keep = [k for k, w in enumerate(rows) if not w["spa"]]
        if len(rows) <= 2 or not keep:
            return False
        longest = max(range(len(rows)), key=lambda k: rows[k]["need"])
        order = [k for k in reversed(range(len(rows))) if k != longest and not rows[k]["spa"]]
        if not order:
            return False
        rows.pop(order[0])
        return True

    while len(rows) > cap and drop_one():
        dropped += 1
    if any(w["spa"] for w in rows):
        while len(rows) > 3 and drop_one():
            dropped += 1
    settle()
    while rows and rows[-1]["e"] > _SIGHT_END and len(rows) > 2 and any((w["s"], w["e"]) != tuple(w["orig"]) for w in rows) and drop_one():
        dropped += 1
        settle()
    kept = {id(w["a"]) for w in rows}
    changed = 0
    for w in rows:
        t = fmt_range(w["s"], w["e"])
        if tuple(w["orig"]) != (w["s"], w["e"]):
            w["a"]["time"] = t
            changed += 1
    if dropped:
        day["activities"] = [a for a in _ensure_list(day.get("activities")) if not (isinstance(a, dict) and any(a is x for x, _ in items) and id(a) not in kept)]
    return changed, dropped


def enforce_stays(itinerary: List[Dict[str, Any]], ctx: Any = None) -> Dict[str, int]:
    """轻松节奏的停留底线：温泉 ≥3.5 小时、博物馆/宫殿 ≥2 小时……不足则拉长并顺延后面的景点；一天塞不下就去掉最后的轻量景点。
    用户明确要紧凑时不强制。"""
    pace = detect_pace(getattr(ctx, "preferences", "") if ctx is not None else "")
    if pace == TIGHT:
        return {"extended": 0, "dropped": 0}
    pool = _pool_index(ctx) if ctx is not None else {}
    citywalk = "citywalk" in str(getattr(ctx, "preferences", "") or "").lower() or "漫步" in str(getattr(ctx, "preferences", "") or "")
    ext = drp = 0
    for d in itinerary:
        if isinstance(d, dict):
            c, x = _enforce_day(d, pool, pace, citywalk)
            ext += c
            drp += x
    return {"extended": ext, "dropped": drp}


def apply(itinerary: List[Dict[str, Any]], ctx: Any = None) -> Dict[str, int]:
    """润色入口：先去重餐厅，再按节奏拉长停留，最后修时间。"""
    d = dedupe_meals(itinerary, ctx) if ctx is not None else 0
    st = enforce_stays(itinerary, ctx)
    from . import feasibility                          # 避免循环导入
    hs = feasibility.apply(itinerary, ctx)             # 营业时间：闭馆/不在营业时段 → 平移、换天、移出或提醒
    return {"deduped": d, "retimed": repair_times(itinerary), **st, **hs}
