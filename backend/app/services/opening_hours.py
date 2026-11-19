"""营业时间（来自 Google Places 的 regularOpeningHours）：压缩存储 + 纯函数判断。

存储格式（随候选地点一起进缓存，约 100 字节）：
    {"p": [[开始星期, 开始分钟, 结束星期, 结束分钟], ...]}   星期 周一=0 … 周日=6；分钟 = 当天 0:00 起算
    {"always": True}                                           全天营业
没有营业时间数据 = None（一律按“未知”处理，绝不编造）。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

WEEK = "一二三四五六日"
GRACE_END = 10          # 结束时间超出营业结束不超过 10 分钟，算在营业内（最后入场通常更早，这里不做更严的推测）

Hours = Dict[str, Any]
Range = Tuple[int, int]


def compact(raw: Any) -> Optional[Hours]:
    """Google regularOpeningHours → 压缩格式；无效/缺失返回 None。"""
    if not isinstance(raw, dict):
        return None
    periods = raw.get("periods")
    if not isinstance(periods, list) or not periods:
        return None
    out: List[List[int]] = []
    for per in periods:
        if not isinstance(per, dict):
            continue
        o, c = per.get("open") or {}, per.get("close")
        if not c:
            if len(periods) == 1:
                return {"always": True}              # 只有开始没有结束 = 全天营业
            continue
        try:
            od, cd = (int(o["day"]) + 6) % 7, (int(c["day"]) + 6) % 7        # Google 周日=0 → 周一=0
            om = int(o.get("hour", 0)) * 60 + int(o.get("minute", 0))
            cm = int(c.get("hour", 0)) * 60 + int(c.get("minute", 0))
        except (KeyError, TypeError, ValueError):
            continue
        out.append([od, om, cd, cm])
    return {"p": out} if out else None


def valid(h: Any) -> bool:
    return isinstance(h, dict) and (bool(h.get("always")) or bool(h.get("p")))


def open_ranges(h: Optional[Hours], dow: int) -> List[Range]:
    """某个星期当天的营业区间（含前一天跨午夜延续到今天的部分）。没有数据返回 []。"""
    if not valid(h):
        return []
    if h.get("always"):
        return [(0, 1440)]
    out: List[Range] = []
    for od, om, cd, cm in h["p"]:
        if od == dow:
            out.append((om, cm if cd == od and cm > om else 1440))
        elif cd == dow and od != cd:
            out.append((0, cm))
    return sorted(out)


def closed_weekdays(h: Optional[Hours]) -> List[int]:
    """每周完全不营业的星期（只在确实有数据、且至少一天营业时才有意义）。"""
    if not valid(h) or h.get("always"):
        return []
    days = [d for d in range(7) if not open_ranges(h, d)]
    return days if len(days) < 7 else []


def check(h: Optional[Hours], dow: int, start: int, end: int) -> Tuple[str, List[Range]]:
    """游览 [start,end)（分钟）在星期 dow 是否在营业内：'unknown' | 'ok' | 'closed' | 'outside'。"""
    if not valid(h):
        return "unknown", []
    rs = open_ranges(h, dow)
    if not rs:
        return "closed", []
    if any(a <= start and end <= b + GRACE_END for a, b in rs):
        return "ok", rs
    return "outside", rs


def fmt(m: int) -> str:
    return "24:00" if m >= 1440 else "%02d:%02d" % (m // 60, m % 60)


def fmt_ranges(rs: List[Range]) -> str:
    return "、".join("%s-%s" % (fmt(a), fmt(b)) for a, b in rs)


def describe_day(h: Optional[Hours], dow: int) -> str:
    """‘周二营业 10:00-18:00’ / ‘周一闭馆’；未知返回空串。"""
    if not valid(h):
        return ""
    rs = open_ranges(h, dow)
    return "周%s营业 %s" % (WEEK[dow], fmt_ranges(rs)) if rs else "周%s不营业" % WEEK[dow]


def describe_week(h: Optional[Hours]) -> str:
    """一周概括：‘周一不营业；其余 09:00-18:00’。"""
    if not valid(h):
        return ""
    if h.get("always"):
        return "全天营业"
    closed = closed_weekdays(h)
    texts = [fmt_ranges(open_ranges(h, d)) for d in range(7) if d not in closed]
    if not texts:
        return ""
    common = max(set(texts), key=texts.count)
    head = ("周" + "、周".join(WEEK[d] for d in closed) + "不营业；") if closed else ""
    return head + ("其余 " if closed else "") + common if texts.count(common) == len(texts) else head + "营业时间各日不同"
