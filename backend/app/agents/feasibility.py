"""营业时间可行性校验（确定性，不调用模型）。

输入：已排好的行程 + 候选池里每个景点的营业时间（Google regularOpeningHours，压缩格式）+ 出发日期。
只处理“确定有问题”的景点：数据缺失一律视为未知，不改动、不提示。
修复顺序：
  1. 当天闭馆 / 时间在营业时段之外 → 先在当天营业时段内平移（不与其它景点、餐饮重叠）；
  2. 平移不行 → 换到附近的另一天（那天营业、有空档、天数没满、离当天路线不远）；
  3. 都不行 → 非必去且当天景点 ≥3 个则移出；否则保留并生成提醒。
没有出发日期 = 不知道星期几 = 不做任何事。
"""

from __future__ import annotations

import datetime as _dt
from typing import Any, Dict, List, Optional, Tuple

from ..services import opening_hours as oh
from ..services.day_geo import _coord, haversine_km
from ..services.itinerary_utils import _ensure_list
from . import polish

_STEP = 15
_PAD = 10                      # 与相邻安排之间至少留的分钟数
_EARLIEST, _LATEST = 7 * 60, 22 * 60
_MAX_PER_DAY = 5
_MOVE_KM = 6.0                 # 换天时，景点离目标那天路线中心的最大距离


def _start(ctx: Any) -> Optional[_dt.date]:
    s = str(getattr(ctx, "start_date", "") or "").strip()[:10]
    try:
        return _dt.date.fromisoformat(s)
    except ValueError:
        return None


def _busy(day: Dict[str, Any], skip: Any = None, meals: bool = True) -> List[Tuple[int, int]]:
    out: List[Tuple[int, int]] = []
    for a in _ensure_list(day.get("activities")):
        if isinstance(a, dict) and a is not skip:
            r = polish.parse_range(a.get("time"))
            if r:
                out.append(r)
    if meals:
        for m in _ensure_list(day.get("meals")):
            if isinstance(m, dict):
                r = polish.parse_range(m.get("time"))
                if r:
                    out.append(r)
    return out


def _fit(h: Dict[str, Any], dow: int, dur: int, orig_s: int, day: Dict[str, Any], skip: Any = None) -> Optional[Tuple[int, int]]:
    """在 dow 当天的营业时段里，找离原开始时间最近、且不与当天其它安排重叠的位置。"""
    for meals in (True, False):
        busy = _busy(day, skip, meals)
        for d in dict.fromkeys((dur, max(60, dur * 2 // 3))):
            cands: List[int] = []
            for a, b in oh.open_ranges(h, dow):
                lo, hi = max(a, _EARLIEST), min(b, _LATEST) - d
                cands.extend(range(lo, hi + 1, _STEP))
                if lo <= hi:
                    cands.append(hi)
            for s in sorted(set(cands), key=lambda x: (abs(x - orig_s), x)):
                if not any(s < y + _PAD and x - _PAD < s + d for x, y in busy):
                    return s, s + d
    return None


def _state(act: Dict[str, Any], pool: Dict[str, Dict[str, Any]], dow: int) -> Tuple[str, Optional[Dict[str, Any]], Optional[Tuple[int, int]], List[Tuple[int, int]]]:
    src = pool.get(str(act.get("name") or "").strip().lower()) or {}
    h = src.get("hours")
    rng = polish.parse_range(act.get("time"))
    if not oh.valid(h) or not rng:
        return "unknown", None, rng, []
    st, rs = oh.check(h, dow, rng[0], rng[1])
    return st, h, rng, rs


def _insert(day: Dict[str, Any], act: Dict[str, Any]) -> None:
    acts = [a for a in _ensure_list(day.get("activities")) if isinstance(a, dict)]
    acts.append(act)
    acts.sort(key=lambda a: (polish.parse_range(a.get("time")) or (9999, 0))[0])
    day["activities"] = acts


def apply(itinerary: List[Dict[str, Any]], ctx: Any = None) -> Dict[str, int]:
    """原地修复；返回统计。无法解决、需要提醒用户的问题写入 ctx.hours_issues（每次重算）。"""
    stats = {"hours_shifted": 0, "hours_moved": 0, "hours_dropped": 0, "hours_unresolved": 0}
    issues: List[str] = []
    if ctx is not None:
        ctx.hours_issues = issues
    base = _start(ctx) if ctx is not None else None
    if base is None:
        return stats
    pool = polish._pool_index(ctx)
    if not any(oh.valid(v.get("hours")) for v in pool.values()):
        return stats
    days = [d for d in itinerary if isinstance(d, dict)]

    def dow_of(d: Dict[str, Any], k: int) -> int:
        n = int(d.get("day") or (k + 1))
        return (base + _dt.timedelta(days=n - 1)).weekday()

    for k, day in enumerate(days):
        dn = int(day.get("day") or (k + 1))
        dow = dow_of(day, k)
        for act in list(_ensure_list(day.get("activities"))):
            if not isinstance(act, dict):
                continue
            st, h, rng, rs = _state(act, pool, dow)
            name = str(act.get("name") or "")
            if st in ("unknown", "ok"):
                if st == "ok":
                    act["open_hint"] = "周%s %s" % (oh.WEEK[dow], oh.fmt_ranges(rs))
                continue
            dur = rng[1] - rng[0]
            fit = _fit(h, dow, dur, rng[0], day, skip=act) if st == "outside" else None
            if fit:
                act["time"] = polish.fmt_range(*fit)
                act["open_hint"] = "周%s %s" % (oh.WEEK[dow], oh.fmt_ranges(rs))
                stats["hours_shifted"] += 1
                continue
            # 换到附近的另一天
            src = pool.get(name.strip().lower()) or {}
            here = _coord(act) or _coord(src)
            moved = False
            if len(_ensure_list(day.get("activities"))) >= 2:
                order = sorted(range(len(days)), key=lambda j: abs(j - k))
                for j in order:
                    if j == k:
                        continue
                    other = days[j]
                    if len(_ensure_list(other.get("activities"))) >= _MAX_PER_DAY:
                        continue
                    ctr = polish._centroid(other)
                    if here and ctr and haversine_km(here, ctr) > _MOVE_KM:
                        continue
                    odow = dow_of(other, j)
                    if not oh.open_ranges(h, odow):
                        continue
                    f2 = _fit(h, odow, dur, rng[0], other)
                    if not f2:
                        continue
                    day["activities"] = [a for a in _ensure_list(day.get("activities")) if a is not act]
                    act["time"] = polish.fmt_range(*f2)
                    act["open_hint"] = "周%s %s" % (oh.WEEK[odow], oh.fmt_ranges(oh.open_ranges(h, odow)))
                    _insert(other, act)
                    issues.append("Day %d：「%s」周%s不营业，已改到 Day %d" % (dn, name, oh.WEEK[dow], int(other.get("day") or (j + 1))) if st == "closed"
                                  else "Day %d：「%s」营业时间与安排冲突，已改到 Day %d" % (dn, name, int(other.get("day") or (j + 1))))
                    stats["hours_moved"] += 1
                    moved = True
                    break
            if moved:
                continue
            n_left = len(_ensure_list(day.get("activities")))
            if st == "closed" and not act.get("must_include") and not src.get("must_include") and n_left >= 3:
                day["activities"] = [a for a in _ensure_list(day.get("activities")) if a is not act]
                issues.append("Day %d：「%s」周%s不营业，已从当天移除" % (dn, name, oh.WEEK[dow]))
                stats["hours_dropped"] += 1
                continue
            if st == "closed":
                issues.append("Day %d：「%s」周%s不营业，建议改期或替换" % (dn, name, oh.WEEK[dow]))
            else:
                issues.append("Day %d：「%s」营业时间 %s，与安排的 %s 不符，建议调整" % (dn, name, oh.fmt_ranges(rs), polish.fmt_range(*rng)))
            stats["hours_unresolved"] += 1
    return stats

