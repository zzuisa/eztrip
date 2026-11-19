"""活动匹配：把 Agent 从网页里提取出的活动，对照用户的实际行程做确定性判定（日期 / 时间 / 地点）。

判定全由代码得出，模型只负责按判定写建议、不得改动。
verdict：fits 适合 / adjust 需调整时间 / near 差几天 / no 不在当天 / unknown 日期不明。
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

NEAR_DAYS = 3
BUFFER = 30  # 分钟：前后活动之间至少留出的路上时间
ORDER = {"fits": 0, "adjust": 1, "near": 2, "unknown": 3, "no": 4}
_ISO = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})(?:[T\s]+(\d{1,2}):(\d{2}))?")
_EU = re.compile(r"(\d{1,2})[./](\d{1,2})[./](\d{4})(?:[T\s]+(\d{1,2}):(\d{2}))?")


def parse_dt(s: Any) -> Tuple[Optional[date], Optional[int]]:
    """'2026-11-14' / '2026-11-14T19:30' / '14/11/2026' / '14.11.2026' → (date, 分钟数或 None)。"""
    t = str(s or "").strip()
    m = _ISO.search(t)
    if m:
        y, mo, d, hh, mm = m.groups()
    else:
        m = _EU.search(t)
        if not m:
            return None, None
        d, mo, y, hh, mm = m.groups()
    try:
        day = date(int(y), int(mo), int(d))
    except ValueError:
        return None, None
    return day, (int(hh) * 60 + int(mm) if hh is not None and int(hh) < 24 and int(mm) < 60 else None)


def parse_window(s: Any) -> Optional[Tuple[int, int]]:
    m = re.search(r"(\d{1,2}):(\d{2})\s*[-–~至到]\s*(\d{1,2}):(\d{2})", str(s or ""))
    if not m:
        return None
    a, b = int(m[1]) * 60 + int(m[2]), int(m[3]) * 60 + int(m[4])
    return (a, b) if b > a else None


def _hm(x: int) -> str:
    return "%02d:%02d" % (x // 60, x % 60)


def _norm(s: str) -> str:
    return re.sub(r"[^\w]+", "", str(s or "").lower())


def where_of(ev_place: str, place: str) -> str:
    a, b = _norm(ev_place), _norm(place)
    if not a:
        return "unknown"
    return "here" if (b and (b in a or a in b)) else "other"


def match(ev: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """ctx: trip_date(date|None) today(date) slots([(开始分钟,结束分钟,名称)]，当天所有已安排的时段) window((a,b)|None，兜底) place(str)。返回 {verdict, why, where}。"""
    start, st_min = parse_dt(ev.get("start"))
    end, en_min = parse_dt(ev.get("end"))
    place_flag = where_of(str(ev.get("place") or ""), str(ctx.get("place") or ""))
    if not start:
        return {"verdict": "unknown", "why": "页面未标注具体日期，暂不排入当日安排", "where": place_flag}
    end = end or start
    if end < start:
        end = start
    ref: date = ctx.get("trip_date") or ctx["today"]
    basis = "行程当天" if ctx.get("trip_date") else "今天"
    rng = start.strftime("%m/%d") if start == end else "%s–%s" % (start.strftime("%m/%d"), end.strftime("%m/%d"))
    if start <= ref <= end:
        if st_min is None:
            if start == end:
                return {"verdict": "fits", "why": "%s有（%s），开场时间待主办方公布，可预留弹性时段" % (basis, rng), "where": place_flag}
            return {"verdict": "fits", "why": "活动期间 %s，%s在期内" % (rng, basis), "where": place_flag}
        # 页面写了时间：每天的开场时间按 st_min 算（多日活动视为每天同一时段），时长取页面写的结束时间，没有就按 2 小时
        ev_end = en_min if (end == start and en_min is not None and en_min > st_min) else st_min + 120
        when_txt = "%s %s–%s" % (basis, _hm(st_min), _hm(min(ev_end, 24 * 60 - 1)))
        slots = ctx.get("slots") or []
        if not slots and ctx.get("window"):
            slots = [(ctx["window"][0], ctx["window"][1], ctx.get("place") or "这里")]
        for a, b, nm in slots:
            if st_min < b + BUFFER and ev_end > a - BUFFER:
                tight = not (st_min < b and ev_end > a)
                why = ("%s，与「%s」（%s–%s）衔接不到 %d 分钟，路上时间不够" % (when_txt, nm, _hm(a), _hm(b), BUFFER)) if tight \
                    else ("%s，与「%s」（%s–%s）时间重叠，不能同时进行" % (when_txt, nm, _hm(a), _hm(b)))
                return {"verdict": "adjust", "why": why + "，需要调整", "where": place_flag}
        if slots:
            return {"verdict": "fits", "why": "%s，不与你当天的安排冲突" % when_txt, "where": place_flag}
        return {"verdict": "fits", "why": "%s开始（行程时间未知，需自行对照）" % when_txt, "where": place_flag}
    gap = (start - ref).days if ref < start else (ref - end).days
    if gap <= NEAR_DAYS:
        word = "晚" if ref < start else "早"
        return {"verdict": "near", "why": "%s（%s）比%s%s %d 天，可考虑调整日期" % (rng, "未开始" if ref < start else "已结束", basis, word, gap), "where": place_flag}
    return {"verdict": "no", "why": "%s，不在%s前后几天内" % (rng, basis), "where": place_flag}


def clean_events(raw: Any, seen_ok, limit: int = 8) -> Tuple[List[Dict[str, Any]], int]:
    """校验模型提交的活动：必须有名称；来源链接必须是本会话读过的页面（防编造）。返回 (有效活动, 被丢弃数)。"""
    out: List[Dict[str, Any]] = []
    dropped = 0
    for e in raw if isinstance(raw, list) else []:
        if not isinstance(e, dict):
            continue
        name = re.sub(r"\s+", " ", str(e.get("name") or "")).strip()[:100]
        url = str(e.get("url") or "").strip()
        if not name or not url.startswith(("http://", "https://")) or not seen_ok(url):
            dropped += 1
            continue
        key = (_norm(name), str(e.get("start") or "")[:10])
        if any((_norm(x["name"]), x["start"][:10]) == key for x in out):
            continue
        out.append({
            "name": name, "start": str(e.get("start") or "")[:25], "end": str(e.get("end") or "")[:25],
            "place": str(e.get("place") or "")[:100], "price": str(e.get("price") or "")[:60],
            "url": url[:300], "evidence": re.sub(r"\s+", " ", str(e.get("evidence") or "")).strip()[:120],
        })
        if len(out) >= limit:
            break
    return out, dropped


def run_match(events: List[Dict[str, Any]], ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    res = [{**e, **match(e, ctx)} for e in events]
    res.sort(key=lambda x: (ORDER.get(x["verdict"], 9), x.get("start") or "9"))
    return res


def format_for_model(matched: List[Dict[str, Any]], dropped: int) -> str:
    lab = {"fits": "适合", "adjust": "需调整", "near": "差几天", "no": "不在当天", "unknown": "日期不明"}
    wh = {"here": "就在这个地点", "other": "在别处", "unknown": "地点未写"}
    lines = ["【程序对照行程的判定——不可改动，只能据此写建议】"]
    for i, e in enumerate(matched, 1):
        bits = [f"{i}. [{lab.get(e['verdict'], '?')}] {e['name']}", e["why"], wh.get(e.get("where"), "")]
        if e.get("place"):
            bits.append("地点：" + e["place"])
        if e.get("price"):
            bits.append("价格：" + e["price"])
        bits.append("来源：" + e["url"])
        lines.append(" | ".join(b for b in bits if b))
    if dropped:
        lines.append(f"（另有 {dropped} 条没有可核实的来源链接，已忽略，不要提及。）")
    if not matched:
        lines.append("没有可用的活动。请如实告知，并给出替代建议（换日期 / 换类别 / 就近的常规去处），不要写“资料较少”或“建议查看官网”。")
    return "\n".join(lines)
