"""最终化（settle）：把“所有会改动行程的确定性步骤”收口到一处，保证审核永远发生在最终数据之后。

背景（为什么需要它）：
    以前的流水线是 生成 → 润色 → 审核/重排 → （审核之后才）取还车/到达时间顺延、移除放不下的活动、
    返程交通、预算、天气、营业时间……审核员看到的从来不是用户最终拿到的行程，于是出现
    “审核说缺取还车和返程，交付时却已经补上/顺延/删除”“评分 58→58”这类自相矛盾。

现在的约定：
    1) settle(plan, meta) 是纯代码、幂等的：重建每天的首/末交通（含取还车手续）、按到达时间与每日可游览窗口
       顺延、去掉放不下的活动、保证返程与还车来得及；之后再做一次硬规则检查（hard_checks）。
    2) 审核（reviewer）只看 settle 之后的行程（含交通/窗口/日落），重排后必须再次 settle 再复审。
    3) 交付前后的任何改动都由 fingerprint 把关：行程指纹与审核时的指纹不一致 = 审核过期，必须重新审核。
    4) 用户编辑行程后同样走 settle + 审核（见 review_stored）。
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from typing import Any, Dict, List, Optional, Tuple

from . import transit_plan as tp
from .itinerary_edit import fmt_range, parse_range

ARRIVE_BUFFER = tp.ARRIVE_BUFFER      # 抵达后到开始游览之间的缓冲（分钟）
DEFAULT_LATEST_END = 22 * 60 + 30     # 没有可游览窗口时，被顺延/受返程约束的那一天最晚收尾
RETURN_LATEST = 23 * 60 + 30          # 末日返程最晚到达（含还车）
END_TOLERANCE = 10                    # 超出窗口结束时间的容差（分钟）
MAX_SHIFT = 6 * 60
STEP = 15
MAX_PASSES = 8

_CLOCK = re.compile(r"(\d{1,2}):(\d{2})")


def clock_minutes(value: Any) -> Optional[int]:
    """'09:30' → 570；'次日 01:20' → 1520；无法解析 → None。"""
    text = str(value or "")
    m = _CLOCK.search(text)
    if not m:
        return None
    base = int(m.group(1)) * 60 + int(m.group(2))
    return base + (1440 if "次日" in text else 0)


def clock_text(value: Any) -> str:
    """'2026-11-13T16:50' → '16:50'。"""
    m = _CLOCK.search(str(value or ""))
    return "%02d:%s" % (int(m.group(1)), m.group(2)) if m else ""


def _days(plan: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [d for d in (plan.get("itinerary") or []) if isinstance(d, dict)]


def _items(day: Dict[str, Any]) -> List[Tuple[str, Dict[str, Any]]]:
    out: List[Tuple[str, Dict[str, Any]]] = []
    for key in ("activities", "meals"):
        for it in day.get(key) or []:
            if isinstance(it, dict):
                out.append((key, it))
    return out


def _range(it: Dict[str, Any]) -> Optional[Tuple[int, int]]:
    s, e = parse_range(it.get("time"))
    if s is None:
        return None
    return s, (e if e is not None else s + int(it.get("duration_minutes") or 60))


def windows(meta: Dict[str, Any]) -> Dict[int, Tuple[int, int]]:
    """meta.day_windows → {day: (start, end)} 分钟。"""
    out: Dict[int, Tuple[int, int]] = {}
    for w in (meta or {}).get("day_windows") or []:
        if not isinstance(w, dict):
            continue
        s, e = clock_minutes(w.get("start")), clock_minutes(w.get("end"))
        try:
            day = int(w.get("day"))
        except (TypeError, ValueError):
            continue
        if s is not None and e is not None and e > s:
            out[day] = (s, e)
    return out


def _leg_arrive(day: Dict[str, Any]) -> Optional[int]:
    t = day.get("transit_start")
    return clock_minutes(t.get("arrive")) if isinstance(t, dict) else None


def earliest_start(plan: Dict[str, Any], meta: Dict[str, Any], idx: int) -> int:
    day = _days(plan)[idx]
    dno = int(day.get("day") or idx + 1)
    floor = windows(meta).get(dno, (0, 0))[0]
    arrive = _leg_arrive(day) if idx == 0 else None
    if arrive is not None:
        floor = max(floor, arrive + ARRIVE_BUFFER)
    return floor


def latest_end(plan: Dict[str, Any], meta: Dict[str, Any], idx: int, shifted: bool = False) -> Optional[int]:
    days = _days(plan)
    day = days[idx]
    dno = int(day.get("day") or idx + 1)
    win = windows(meta).get(dno)
    t = day.get("transit_end")
    if win and idx == len(days) - 1 and isinstance(t, dict) and t.get("kind") == "return" and t.get("minutes") is not None:
        # 时间窗是“出发 → 回到出发地”：最后一天要在窗口结束前到家（含还车），所以最后一项必须早到留得出返程 + 30 分钟缓冲
        return win[1] - int(t["minutes"]) - 30
    if win:
        return win[1] + END_TOLERANCE
    if shifted or (idx == len(days) - 1 and isinstance(day.get("transit_end"), dict)):
        return DEFAULT_LATEST_END
    return None


def _return_violation(day: Dict[str, Any], return_ceiling: Optional[int] = None) -> bool:
    t = day.get("transit_end")
    if not isinstance(t, dict) or t.get("kind") != "return":
        return False
    arrive = clock_minutes(t.get("arrive"))
    return arrive is not None and arrive > (return_ceiling or RETURN_LATEST)


def _push(day: Dict[str, Any], floor: int) -> int:
    """把早于 floor 的安排依次推到 floor 之后（保持时长）；后面本来就够晚的不动。返回最大推迟分钟数。"""
    rows = sorted([(r[0], r[1], it) for _k, it in _items(day) for r in [_range(it)] if r], key=lambda x: (x[0], x[1]))
    cur, moved = floor, 0
    for s0, e0, it in rows:
        if s0 < cur:
            ns = -(-cur // 5) * 5
            it["time"] = fmt_range(ns, ns + (e0 - s0))
            moved = max(moved, ns - s0)
            cur = ns + (e0 - s0) + 5
        # 本来就够晚的不动、也不推进 cur（长时间停留里包含一餐是正常安排，不能因为重叠被一起往后推）
    # 推到上午十点半之后的“早餐”没有意义
    day["meals"] = [m for m in (day.get("meals") or [])
                    if not (isinstance(m, dict) and str(m.get("type")) == "breakfast" and (_range(m) or (0, 0))[0] > 10 * 60 + 30)]
    return moved


def _fit_pass(plan: Dict[str, Any], meta: Dict[str, Any], notes: List[str], touched: Dict[int, Dict[str, Any]]) -> bool:
    changed = False
    days = _days(plan)
    for i, day in enumerate(days):
        dno = int(day.get("day") or i + 1)
        rows = [(it, _range(it)) for _k, it in _items(day)]
        rows = [(it, r) for it, r in rows if r]
        if not rows:
            continue
        # 1) 开始太早（抵达前 / 早于可游览窗口）→ 整天顺延
        first = min(r[0] for _it, r in rows)
        floor = earliest_start(plan, meta, i)
        if i == 0 and first > floor + 30 and isinstance(day.get("transit_start"), dict) and windows(meta).get(dno) and not touched.get(dno, {}).get("pulled"):
            # 到达后不该空等：第一项应紧跟抵达（+缓冲）。整天一起提前，保持彼此的先后和间隔
            gap = (first - floor) // 5 * 5
            for _k, it in _items(day):
                r = _range(it)
                if r:
                    it["time"] = fmt_range(r[0] - gap, r[1] - gap)
            info = touched.setdefault(dno, {"shift": 0, "dropped": []})
            info["pulled"] = gap
            changed = True
            continue
        if first < floor:
            moved = _push(day, floor)
            info = touched.setdefault(dno, {"shift": 0, "dropped": []})
            info["shift"] = max(info["shift"], moved)
            changed = True
            continue
        # 2) 收尾太晚（超出可游览窗口 / 末日返程与还车来不及）→ 去掉最晚的、放不下的安排
        shifted = bool(touched.get(dno, {}).get("shift"))
        limit = latest_end(plan, meta, i, shifted)
        over_return = i == len(days) - 1 and _return_violation(day, (windows(meta).get(dno) or (0, 0))[1] or None)
        late = [(it, r) for it, r in rows if limit is not None and r[1] > limit]
        if not late and not over_return:
            continue
        acts = [a for a in (day.get("activities") or []) if isinstance(a, dict)]
        pool = late if late else rows
        victim, _r = max(pool, key=lambda x: (x[1][1], x[1][0]))
        is_meal = any(victim is m for m in (day.get("meals") or []))
        if not is_meal and len(acts) <= 1:
            # 当天只剩一个景点：不删。只超出可游览时间的，把它的结束时间收到窗口内（至少留 60 分钟）
            if late and all(it is victim for it, _ in late) and limit is not None:
                s0, e0 = _range(victim) or (0, 0)
                if limit - s0 >= 60 and e0 > limit:
                    victim["time"] = fmt_range(s0, limit - END_TOLERANCE if limit - END_TOLERANCE - s0 >= 60 else limit)
                    touched.setdefault(dno, {"shift": 0, "dropped": []})["clipped"] = True
                    changed = True
                continue
            if not late or all(it is victim for it, _ in late):
                continue
            victim, _r = max([x for x in late if x[0] is not victim] or late, key=lambda x: (x[1][1], x[1][0]))
            is_meal = any(victim is m for m in (day.get("meals") or []))
        key = "meals" if is_meal else "activities"
        day[key] = [x for x in (day.get(key) or []) if x is not victim]
        touched.setdefault(dno, {"shift": 0, "dropped": []})["dropped"].append(str(victim.get("name") or ""))
        changed = True
    return changed


def settle(plan: Dict[str, Any], meta: Dict[str, Any], *, fit: bool = True, fares: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """原地把 plan 排定为“可交付的最终时间线”，返回 {notes, checks, fingerprint}。

    fit=False 只重建交通（用户手动编辑后：不替用户改动行程，只如实检查并交给审核）。
    幂等：对结果再次调用不会再改动任何东西。
    """
    meta = meta or {}
    tp.build(plan, meta, fares)
    touched: Dict[int, Dict[str, Any]] = {}
    if fit and _days(plan):
        for _ in range(MAX_PASSES):
            if not _fit_pass(plan, meta, [], touched):
                break
            tp.build(plan, meta, fares)
    notes: List[str] = []
    for dno in sorted(touched):
        info = touched[dno]
        parts = []
        if info.get("pulled") and not info["shift"]:
            parts.append("行程整体提前 %s 小时，抵达后直接开始" % round(info["pulled"] / 60, 1))
        if info["shift"]:
            parts.append("起点顺延 %s 小时（抵达/取车/换乘需要时间）" % round(info["shift"] / 60, 1))
        dropped = [n for n in info["dropped"] if n]
        if dropped:
            parts.append("为保证来得及返程/不超出可游览时间，已移除放不下的：" + "、".join(dropped)[:60])
        if parts:
            notes.append("Day %d 已按抵达/取车/返程时间排定：%s" % (dno, "；".join(parts)))
    return {"notes": notes, "checks": hard_checks(plan, meta), "fingerprint": fingerprint(plan)}


def hard_checks(plan: Dict[str, Any], meta: Dict[str, Any]) -> List[Dict[str, Any]]:
    """纯代码的硬规则检查（settle 之后仍不满足的才会返回）。"""
    out: List[Dict[str, Any]] = []
    days = _days(plan)
    wins = windows(meta or {})
    for i, day in enumerate(days):
        dno = int(day.get("day") or i + 1)
        rows = sorted([(r, it) for _k, it in _items(day) for r in [_range(it)] if r], key=lambda x: x[0])
        for (a, ia), (b, ib) in zip(rows, rows[1:]):
            long_stay = max(a[1] - a[0], b[1] - b[0]) > 150      # 长时间停留（购物/乐园）里包含一餐，是正常安排
            if b[0] < a[1] - 5 and not (long_stay and (ia in (day.get("meals") or []) or ib in (day.get("meals") or []))):
                out.append({"day": dno, "code": "overlap", "message": "Day %d「%s」与「%s」时间重叠" % (dno, ia.get("name"), ib.get("name"))})
        if rows:
            floor = earliest_start(plan, meta or {}, i)
            if rows[0][0][0] < floor - 5:
                out.append({"day": dno, "code": "too_early", "message": "Day %d 的首个安排早于可开始时间 %s" % (dno, fmt_range(floor, floor + 1)[:5])})
            limit = latest_end(plan, meta or {}, i, False) if dno in wins else None
            if limit is not None and rows[-1][0][1] > limit and len([1 for _k, it in _items(day)]) > 1:
                out.append({"day": dno, "code": "too_late", "message": "Day %d 的安排超出可游览时间 %s" % (dno, fmt_range(wins[dno][1], wins[dno][1] + 1)[:5])})
        ceiling = wins[dno][1] if (dno in wins and i == len(days) - 1) else None
        if _return_violation(day, ceiling):
            out.append({"day": dno, "code": "return_late", "message": "Day %d 返程与还车到达时间晚于 %s" % (dno, fmt_range(ceiling, ceiling + 1)[:5] if ceiling else "23:30")})
    return out


def fingerprint(plan: Dict[str, Any]) -> str:
    """行程内容指纹：地点/时间/坐标 + 每天首末交通的关键字段。图片、预算、文案不参与（它们不改变“能不能走通”）。"""
    rows: List[Any] = []
    for i, day in enumerate(_days(plan)):
        entry: List[Any] = [int(day.get("day") or i + 1)]
        for key in ("activities", "meals"):
            for it in day.get(key) or []:
                if isinstance(it, dict):
                    def r(v: Any) -> Any:
                        try:
                            return round(float(v), 4)
                        except (TypeError, ValueError):
                            return None
                    entry.append([key[0], str(it.get("name") or ""), str(it.get("time") or ""), r(it.get("latitude")), r(it.get("longitude"))])
        for key in ("transit_start", "transit_end"):
            t = day.get(key)
            entry.append([key, t.get("mode"), t.get("minutes"), t.get("depart"), t.get("arrive"),
                          (t.get("from") or {}).get("name"), (t.get("to") or {}).get("name")] if isinstance(t, dict) else [key])
        rows.append(entry)
    return hashlib.sha1(json.dumps(rows, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]


def is_reviewed(plan: Dict[str, Any]) -> bool:
    """交付/读取时的把关：审核指纹必须等于当前行程指纹。"""
    rv = plan.get("review")
    # skipped/failed 也算“已尝试审核”（审核服务不可用不应让每次读取都重试）；下次行程变化指纹就会变
    return isinstance(rv, dict) and bool(rv.get("fingerprint")) and rv.get("fingerprint") == fingerprint(plan)


def day_constraints(plan: Dict[str, Any], meta: Dict[str, Any], day_no: int) -> str:
    """给编排器重排某一天时附上的硬约束（与 settle 用同一套规则，避免重排出来又被 settle 删改）。"""
    days = _days(plan)
    idx = next((i for i, d in enumerate(days) if int(d.get("day") or i + 1) == day_no), None)
    if idx is None:
        return ""
    day = days[idx]
    parts = []
    floor = earliest_start(plan, meta or {}, idx)
    if floor > 0:
        parts.append("最早 %s 才能开始第一项（旅途时间窗从出发算起，已含出发、路程、取车/抵达缓冲）" % fmt_range(floor, floor + 1)[:5])
    limit = latest_end(plan, meta or {}, idx, idx == 0)
    if limit is not None:
        parts.append("最后一项必须在 %s 前结束（之后还要返程）" % fmt_range(limit, limit + 1)[:5])
    t = day.get("transit_end")
    if isinstance(t, dict) and t.get("kind") == "return":
        w = windows(meta or {}).get(day_no)
        parts.append("结束后还要用约 %s 分钟返回并还车，返程到达不得晚于 %s" % (t.get("minutes"), fmt_range(w[1], w[1] + 1)[:5] if w and idx == len(days) - 1 else "23:30"))
    return "；".join(parts)


def transit_brief(t: Any) -> str:
    if not isinstance(t, dict):
        return ""
    f, to = (t.get("from") or {}).get("name") or "", (t.get("to") or {}).get("name") or ""
    bits = ["%s→%s" % (f[:24], to[:24]), "%s %s分钟" % (t.get("mode_label") or t.get("mode") or "", t.get("minutes"))]
    if t.get("depart"):
        bits.append("出发%s" % t["depart"])
    if t.get("arrive"):
        bits.append("到达%s" % t["arrive"])
    if t.get("note") and "取车" in str(t.get("note")):
        bits.append("含取还车手续45分钟")
    return "，".join(bits)

