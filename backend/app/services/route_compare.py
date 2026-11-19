"""城际路段的「路线对比」：把行程里的出发/到达/返程/跨城路段交给 travel_prices MCP 的 compare_routes，
得到公共交通（逐段月票判定 + 票价）与自驾的多方案对比，用户选定后写回路段与预算。

分工（价格与月票判断一律来自 MCP 的代码，不让模型编数字）：
- MCP：Google Routes 取多条候选 → Deutschlandticket 逐段判定 → FlixBus 实时价/DB 估算 → 自驾油电费 → 排序与推荐；
- 本模块：从行程路段生成请求、保存对比结果与用户的选择（payload["route_compare"] / ["route_choices"]）、
  行程被编辑后让选择继续有效（apply_choice 在 transit_plan.build 里调用）。
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Any, Dict, Optional, Tuple

KINDS = ("transit_start", "transit_end")
FUELS = ("petrol", "diesel", "hybrid", "electric")
ARRIVE_BUFFER = 30


class CompareError(ValueError):
    pass


def clean_prefs(raw: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    raw = raw or {}
    ticket = "none" if str(raw.get("ticket") or "d_ticket") == "none" else "d_ticket"
    try:
        bc = int(raw.get("bahncard") or 0)
    except (TypeError, ValueError):
        bc = 0
    try:
        pax = int(raw.get("passengers") or 1)
    except (TypeError, ValueError):
        pax = 1
    fuel = str(raw.get("fuel") or "petrol")
    try:
        cons = float(raw.get("consumption") or 0)
    except (TypeError, ValueError):
        cons = 0.0
    return {"ticket": ticket, "bahncard": bc if bc in (0, 25, 50) else 0, "passengers": max(1, min(pax, 8)),
            "fuel": fuel if fuel in FUELS else "petrol", "consumption": cons if 0 < cons <= 40 else 0.0}


def key_of(day_no: int, kind: str) -> str:
    return f"{int(day_no)}:{kind}"


def is_comparable(leg: Dict[str, Any]) -> bool:
    """能不能打开「路线对比」：城际路段，或出发 / 返程 / 换城里不太短的路段（避免 60 公里被当成“本地”，只能看到一个打车价）。"""
    if not isinstance(leg, dict):
        return False
    if leg.get("intercity"):
        return True
    try:
        km = float(leg.get("distance_km") or 0)
    except (TypeError, ValueError):
        km = 0.0
    return leg.get("kind") in ("arrival", "return", "intercity") and km >= 8.0


def find_leg(payload: Dict[str, Any], day_no: int, kind: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    if kind not in KINDS:
        raise CompareError("路段类型不合法")
    for i, d in enumerate(payload.get("itinerary") or []):
        if isinstance(d, dict) and int(d.get("day") or i + 1) == int(day_no):
            leg = d.get(kind)
            if not isinstance(leg, dict):
                raise CompareError("这一天没有这段交通")
            if not is_comparable(leg):
                raise CompareError("这一段路程太短，不需要路线对比")
            return d, leg
    raise CompareError("找不到这一天")


def sig_of(leg: Dict[str, Any]) -> str:
    def p(e: Dict[str, Any]) -> str:
        try:
            return f"{round(float(e.get('lat')), 2)},{round(float(e.get('lng')), 2)}"
        except (TypeError, ValueError):
            return "?"
    return f"{p(leg.get('from') or {})}>{p(leg.get('to') or {})}"


def depart_local(meta: Dict[str, Any], day_no: int, leg: Dict[str, Any]) -> Optional[str]:
    """路段计划出发的当地时间（无时区的 ISO，MCP 按欧洲当地时间理解）。没有开始日期就返回 None（用「现在」）。"""
    try:
        d0 = dt.date.fromisoformat(str(meta.get("start_date") or "")[:10])
    except ValueError:
        return None
    m = re.match(r"^(\d{1,2}):(\d{2})$", str(leg.get("depart") or ""))
    hh, mm = (int(m.group(1)), int(m.group(2))) if m else (8, 0)
    d = d0 + dt.timedelta(days=max(0, int(day_no) - 1))
    return f"{d.isoformat()}T{hh:02d}:{mm:02d}:00"


def mcp_args(payload: Dict[str, Any], day_no: int, kind: str, prefs: Dict[str, Any]) -> Dict[str, Any]:
    _, leg = find_leg(payload, day_no, kind)
    a, b = leg.get("from") or {}, leg.get("to") or {}
    args: Dict[str, Any] = {
        "origin": str(a.get("name") or "出发地"), "destination": str(b.get("name") or "目的地"),
        "origin_lat": a.get("lat"), "origin_lng": a.get("lng"), "dest_lat": b.get("lat"), "dest_lng": b.get("lng"),
        "ticket": prefs["ticket"], "bahncard": prefs["bahncard"], "passengers": prefs["passengers"], "fuel": prefs["fuel"],
        "consumption": prefs["consumption"],
    }
    dep = depart_local(payload.get("trip_meta") or {}, day_no, leg)
    if dep:
        args["depart"] = dep
    return {k: v for k, v in args.items() if v is not None}


async def fetch(args: Dict[str, Any]) -> Dict[str, Any]:
    from . import budget as budget_svc

    if not budget_svc.mcp_available():
        raise CompareError("路线对比服务暂不可用")
    res = await budget_svc._acall("compare_routes", args)
    if not isinstance(res, dict) or not res:
        raise CompareError("路线对比服务没有返回结果，请稍后再试")
    return res


# ---------------------------------------------------------------- 存储用的精简结构


def compact(opt: Dict[str, Any]) -> Dict[str, Any]:
    """保存到路段上的选择：只留展示和重算需要的字段。"""
    base = {k: opt.get(k) for k in ("id", "kind", "price", "price_low", "price_high", "price_confidence", "duration_min", "tags") if k in opt}
    if opt.get("kind") == "drive":
        c = opt.get("cost") or {}
        base.update(distance_km=opt.get("distance_km"), cost={k: c.get(k) for k in ("fuel", "energy_cost", "toll", "total", "notes", "unit", "consumption")})
        return base
    legs = []
    for l in opt.get("legs") or []:
        if l.get("mode") == "WALK":
            legs.append({"mode": "WALK", "minutes": l.get("minutes")})
            continue
        f = l.get("fare") or {}
        legs.append({"mode": "TRANSIT", "line": l.get("line"), "agency": l.get("agency"), "status": l.get("status"), "reason": l.get("reason"),
                     "category": l.get("category"), "from": (l.get("from") or {}).get("name"), "to": (l.get("to") or {}).get("name"),
                     "dep": l.get("dep"), "arr": l.get("arr"), "minutes": l.get("minutes"),
                     "fare": {k: f.get(k) for k in ("amount", "low", "high", "source", "confidence", "basis", "link") if k in f} or None})
    base.update(depart=opt.get("depart"), arrive=opt.get("arrive"), transfers=opt.get("transfers"), passengers=opt.get("passengers"), legs=legs)
    return base


def _hm(s: Any) -> Optional[int]:
    m = re.match(r"^(\d{1,2}):(\d{2})$", str(s or ""))
    return int(m.group(1)) * 60 + int(m.group(2)) if m else None


def apply_choice(plan: Dict[str, Any], day_no: int, kind: str, leg: Dict[str, Any], first_start: Optional[int] = None) -> bool:
    """用户选定的方案覆盖这一段的估算（里程估算 → 真实路线与票价）。路段变了（起终点对不上）就忽略。"""
    ch = (plan.get("route_choices") or {}).get(key_of(day_no, kind))
    if not isinstance(ch, dict) or ch.get("sig") != sig_of(leg) or not isinstance(ch.get("opt"), dict):
        return False
    opt = ch["opt"]
    leg["route_choice"] = opt
    leg["minutes"] = int(opt.get("duration_min") or leg.get("minutes") or 0)
    leg["cost"] = round(float(opt.get("price") or 0), 2)
    conf = str(opt.get("price_confidence") or "estimate")
    leg["confidence"] = "live" if conf in ("live", "pass") else "estimate"
    if opt.get("kind") == "drive":
        leg["mode"], leg["mode_label"] = "drive", "自驾"
        if opt.get("distance_km"):
            leg["distance_km"] = round(float(opt["distance_km"]))
        leg["note"] = "油费/电费 + 过路费估算，不含停车"
        leg.pop("depart", None), leg.pop("arrive", None)
        leg.pop("warning", None), leg.pop("late_min", None)
        return True
    leg["mode"], leg["mode_label"] = "transit", "公共交通"
    leg["note"] = "月票内线路不另付" if opt.get("price_confidence") == "pass" else "仅月票外的路段计费"
    if opt.get("depart"):
        leg["depart"], leg["arrive"] = opt["depart"], opt.get("arrive")
    leg.pop("warning", None), leg.pop("late_min", None)
    arr, dep = _hm(opt.get("arrive")), _hm(opt.get("depart"))
    if kind == "transit_start" and first_start is not None and arr is not None and dep is not None:
        arr_abs = arr if arr >= dep else arr + 1440
        if arr_abs<dep+int(opt.get('duration_min') or 0)-120:
            arr_abs += 1440*max(0,(dep+int(opt.get('duration_min') or 0)-arr_abs)//1440)
        from .transit_plan import absolute_time
        leg['arrival_day_offset']=arr_abs//1440
        leg['arrive']=absolute_time(arr_abs)
        late = arr_abs + ARRIVE_BUFFER - first_start
        if late > 20:
            leg["late_min"] = int(late)
            leg["warning"] = f"按 {opt.get('depart')} 出发约 {opt.get('arrive')} 到达，比当天首站晚约 {round(late / 60, 1)} 小时：建议把上午的安排顺延"
    return True


# ---------------------------------------------------------------- 文案校验


_EUR = re.compile(r"(?:€|EUR)\s*(\d+(?:[.,]\d+)?)|(\d+(?:[.,]\d+)?)\s*(?:€|欧元|欧|EUR)", re.I)


def allowed_amounts(result: Dict[str, Any]) -> set:
    vals = {63.0}
    for m in _EUR.finditer(str(result.get("why") or "")):   # 综合推荐理由里的差价也是程序算的，允许引用
        vals.add(float((m.group(1) or m.group(2)).replace(",", ".")))
    for o in result.get("options") or []:
        for k in ("price", "price_low", "price_high"):
            if o.get(k) is not None:
                vals.add(float(o[k]))
        c = o.get("cost") or {}
        for k in ("energy_cost", "toll", "total"):
            if c.get(k) is not None:
                vals.add(float(c[k]))
        for l in o.get("legs") or []:
            f = l.get("fare") or {}
            for k in ("amount", "low", "high"):
                if f.get(k) is not None:
                    vals.add(float(f[k]))
    return vals


def sanitize_advice(text: Any, result: Dict[str, Any], limit: int = 200) -> Optional[str]:
    """模型写的建议里出现的每一个金额，都必须能在数据里找到（±0.6 欧，允许四舍五入）；否则丢弃改用规则文案。"""
    t = re.sub(r"\s+", " ", str(text or "")).strip()
    if not t or len(t) > limit * 2 or re.search(r"\bAI\b|人工智能|作为.{0,4}模型|(?<![A-Za-z0-9])[td]\d{1,2}(?![A-Za-z0-9])", t):
        return None
    allowed = allowed_amounts(result)
    for m in _EUR.finditer(t):
        v = float((m.group(1) or m.group(2)).replace(",", "."))
        if not any(abs(v - a) <= 0.6 for a in allowed):
            return None
    return t[: limit * 2]

