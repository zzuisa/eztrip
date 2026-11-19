"""每天的「第一程 / 最后一程」交通：把出发地、住宿、跨城切换都落成结构化的路段（纯代码，不耗模型）。

- Day 1 开头：出发地 → 目的地（同城按出行偏好；外地按距离选火车/自驾/飞机，并给出建议出发时间与到达是否来得及）；
- 之后每天开头：住宿 → 当天第一站；若这一天的第一站离住宿很远（多地点切换），则改为上一站 → 新城市的城际路段；
- 最后一天结尾：当天最后一站 → 返回出发地。
结果写在行程每一天的 transit_start / transit_end 字段里；金额是按里程估算，来源会标注，不冒充实时票价。
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

from . import route_compare as rc
from . import stay_plan as sp
from .itinerary_edit import fmt_minutes, item_start, parse_range
from .origin import clean_origin

LOCAL_KM = 30.0          # 直线超过它就按城际处理（可对比公交 / 自驾）；60 公里的路程不该被当成“本地”再算成打车
TAXI_MAX_KM = 15.0       # 「混合」偏好下，自动安排打车的单段上限（再远一律公共交通 / 城际，不替用户选最贵的方式）
COMPARE_MIN_KM = 8.0     # 出发 / 返程 / 换城 路段只要不太短，就允许打开「路线对比」
STAY_NEAR_KM = 40.0      # 住宿离当天第一站不超过它，才把住宿当作当天起点
ARRIVE_BUFFER = 15       # 到站后到开始游览之间的缓冲（分钟）
DEFAULT_DEPART = 7 * 60 + 30
EARLIEST_DEPART = 5 * 60 + 30

MODE_LABEL = {"walk": "步行", "transit": "公共交通", "drive": "自驾", "taxi": "打车", "train": "火车", "flight": "飞机"}


def window_of(meta: Dict[str, Any], day_no: int) -> Optional[Tuple[int, int]]:
    """用户给的当天时间窗（分钟）。含义：第一天 = 从出发地出发的最早时间；最后一天 = 回到出发地(含还车)的最晚时间。"""
    for w in (meta or {}).get("day_windows") or []:
        try:
            if int(w.get("day")) != int(day_no):
                continue
            a, b = parse_range("%s-%s" % (w.get("start"), w.get("end")))
        except (TypeError, ValueError, AttributeError):
            continue
        if a is not None and b is not None and b > a:
            return a, b
    return None


def _pref(meta: Dict[str, Any]) -> str:
    return str(meta.get("transportation") or "")


def _drive_pref(pref: str) -> bool:
    return any(x in pref for x in ("自驾", "开车", "租车", "驾车"))


def _pt(lat: Any, lng: Any) -> Optional[Tuple[float, float]]:
    try:
        a, b = float(lat), float(lng)
    except (TypeError, ValueError):
        return None
    return (a, b) if -90 <= a <= 90 and -180 <= b <= 180 else None


def origin_point(meta: Dict[str, Any]) -> Optional[Tuple[float, float]]:
    return _pt(meta.get("origin_lat"), meta.get("origin_lng")) if clean_origin(meta.get("origin")) else None


def _local_mode(pref: str, d: float) -> str:
    p = pref or ""
    if "步行" in p:
        return "walk" if d <= 3.0 else "transit"
    if _drive_pref(p):
        return "walk" if d <= 0.4 else "drive"
    if "混合" in p:
        return "walk" if d <= 1.0 else ("taxi" if 8.0 < d <= TAXI_MAX_KM else "transit")
    return "walk" if d <= 0.9 else "transit"


def _local_minutes(mode: str, d: float) -> int:
    if mode == "walk":
        return max(1, round(d / 4.8 * 60))
    if mode == "transit":
        return round(d / 18 * 60 + 8)
    if mode == "taxi":
        return round(d / 28 * 60 + 4)
    return round(d / 30 * 60 + 5)


def _local_cost(mode: str, d: float, fares: Dict[str, Any]) -> float:
    if mode == "walk":
        return 0.0
    if mode == "transit":
        return float(fares.get("single", 2.4))
    if mode == "taxi":
        return float(fares.get("taxi_base", 3.5)) + float(fares.get("taxi_per_km", 1.6)) * d
    return d * 0.11


def _intercity_mode(pref: str, straight: float, meta=None) -> str:
    if _drive_pref(pref):
        return "drive"
    choice=(meta or {}).get('longhaul_mode','ground')
    if any(x in pref for x in ('飞机','航空','航班')):return 'flight'
    if choice=='flight':return 'flight' if straight>650 else 'train'
    if choice=='auto':return 'flight' if straight>650 else 'train'
    return 'train' 


def _intercity(mode: str, straight: float) -> Tuple[float, int, float, str]:
    """返回 (路程km, 分钟, 估算费用, 说明)。费用是按里程的经验估算，不是实时票价。"""
    if mode == "flight":
        minutes = round(150 + straight / 720 * 60)
        return straight, minutes, round(35 + 0.065 * straight), "含往返机场与安检的缓冲；机票随日期浮动很大"
    road = straight * 1.25
    if mode == "drive":
        return road, round(road / 85 * 60 + max(0, road // 200) * 15), round(road * 0.11 + road * 0.05), "油费 + 过路费估算，不含停车"
    speed = 115.0 if straight >= 150 else 75.0
    return road, round(road / speed * 60 + 25), max(9, round(road * 0.15)), "按普通票价估算；提前订票通常更便宜"


def _first(day: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    rows = []
    for i, a in enumerate(day.get("activities") or []):
        if isinstance(a, dict) and sp._coord(a):
            rows.append((item_start(a, False), 0, i, a))
    for i, m in enumerate(day.get("meals") or []):
        if isinstance(m, dict) and sp._coord(m):
            rows.append((item_start(m, True), 1, i, m))
    rows.sort(key=lambda r: (r[0], r[1], r[2]))
    return rows[0][3] if rows else None


def _last(day: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    best = None
    for is_meal, key in ((False, "activities"), (True, "meals")):
        for it in day.get(key) or []:
            if isinstance(it, dict) and sp._coord(it):
                s, e = parse_range(it.get("time"))
                st = item_start(it, is_meal)
                end = e if e is not None else st + 90
                if best is None or end >= best[0]:
                    best = (end, it)
    return best[1] if best else None


def _end_minute(item: Dict[str, Any], is_meal: bool = False) -> int:
    s, e = parse_range(item.get("time"))
    st = item_start(item, is_meal)
    return e if e is not None else st + int(item.get("duration_minutes") or 90)


def _end(name: str, p: Tuple[float, float]) -> Dict[str, Any]:
    return {"name": name[:80], "lat": round(p[0], 6), "lng": round(p[1], 6)}


def _leg(kind: str, a_name: str, a: Tuple[float, float], b_name: str, b: Tuple[float, float], meta: Dict[str, Any],
         fares: Dict[str, Any], first_start: Optional[int] = None, after_end: Optional[int] = None,
         depart_floor: Optional[int] = None) -> Dict[str, Any]:
    straight = sp.km(a, b)
    pref = _pref(meta)
    out: Dict[str, Any] = {"kind": kind, "from": _end(a_name, a), "to": _end(b_name, b)}
    if straight <= LOCAL_KM:
        d = sp.road_km(a, b)
        mode = _local_mode(pref, d)
        minutes = _local_minutes(mode, d)
        out.update(mode=mode, distance_km=round(d, 1), minutes=minutes, cost=round(_local_cost(mode, d, fares), 1), intercity=False)
    else:
        mode = _intercity_mode(pref, straight, meta)
        d, minutes, cost, note = _intercity(mode, straight)
        out.update(mode=mode, distance_km=round(d), minutes=int(minutes), cost=float(cost), intercity=True, note=note)
    out["mode_label"] = MODE_LABEL.get(out["mode"], "")
    if out['mode']=='flight':
        out['verification']='unverified_flight'
        out['note']='仅为门到门航程与费用估算，未核实实际航班、机场和座位；请先确认班次。'
    else:out['verification']='estimate' 
    if out['intercity'] and out['minutes'] >= 300 and out['mode'] != 'drive':
        timing = meta.get('longhaul_timing', 'balanced')
        advice = ('优先白天出行，避免凌晨换乘' if timing == 'day' else
                  '可对比直达卧铺/可躺座夜班；先核实班次、卧铺价格和到站交通，次日预留休息与行李寄存。未确认前保留住宿预算')
        out['note'] = (out.get('note') or '') + '；' + advice + '（出发到达时间为估算，非真实班次）'
    if not out["intercity"] and depart_floor is not None and kind == "arrival":
        out["depart"], out["arrive"] = fmt_minutes(depart_floor), fmt_minutes(depart_floor + out["minutes"])
    out["confidence"] = "estimate"
    out["comparable"] = rc.is_comparable(out)
    # 时间提示：只对城际路段，且只在能确定“首站时间/收尾时间”时给
    if out["intercity"]:
        if kind in ("arrival", "intercity") and first_start is not None:
            ideal = first_start - ARRIVE_BUFFER - out["minutes"]
            if depart_floor is not None:
                depart = depart_floor      # 用户的时间窗从“出发”算起：不早于它，也不白白空等
            else:
                depart = max(EARLIEST_DEPART, min(DEFAULT_DEPART, ideal)) if ideal >= EARLIEST_DEPART else DEFAULT_DEPART
            arrive = depart + out["minutes"]
            out["depart"], out["arrive"] = fmt_minutes(depart), fmt_minutes(arrive)
            late = arrive + ARRIVE_BUFFER - first_start
            if late > 20:
                h = round(late / 60, 1)
                out["warning"] = f"按 {out['depart']} 出发约 {out['arrive'] if arrive < 1440 else '次日'} 到达，比当天首站晚约 {h} 小时：建议把上午的安排顺延，或前一晚出发"
                out["late_min"] = int(late)
        elif kind == "return" and after_end is not None:
            depart = after_end + 30
            arrive = depart + out["minutes"]
            out["depart"] = fmt_minutes(depart)
            out["arrive"] = fmt_minutes(arrive) if arrive < 1440 else "次日 " + fmt_minutes(arrive - 1440)
            if arrive >= 1440 - 30:
                out["warning"] = "返程到达会接近或超过午夜，建议提前结束最后一天的行程或改乘更早的班次"
    return out


def night_stay(meta, night):
    value = next((s for s in meta.get('stays', []) if s.get('night') == night), None)
    if value:
        return _pt(value.get('lat'), value.get('lng')), value.get('name') or '住宿区域'
    return sp.stay_point(meta), sp.clean_stay(meta.get('stay_name')) or '住宿'


def build(plan: Dict[str, Any], meta: Dict[str, Any], fares: Optional[Dict[str, Any]] = None) -> None:
    """原地写入 plan['itinerary'][i]['transit_start'/'transit_end']；不满足条件的天删除旧字段。"""
    itin = [d for d in (plan.get("itinerary") or []) if isinstance(d, dict)]
    f = fares or ((plan.get("total_budget") or {}).get("detail") or {}).get("fares") or {}
    origin = origin_point(meta)
    oname = clean_origin(meta.get("origin")) or "出发地"
    return_info = meta.get('return_point') or {}
    return_point = _pt(return_info.get('lat'), return_info.get('lng')) or origin
    return_name = clean_origin(return_info.get('name')) or oname
    stay = sp.stay_point(meta)
    sname = sp.clean_stay(meta.get("stay_name")) or "住宿"
    prev_last: Optional[Dict[str, Any]] = None
    for i, day in enumerate(itin):
        day.pop("transit_start", None)
        day.pop("transit_end", None)
        stay, sname = night_stay(meta, max(1, i))
        end_stay, end_sname = night_stay(meta, i + 1)
        first, last = _first(day), _last(day)
        if not first:
            continue
        fp = sp._coord(first)
        fs = item_start(first, first in (day.get("meals") or []))
        fname = str(first.get("name") or "第一站")
        t: Optional[Dict[str, Any]] = None
        w0 = window_of(meta, int(day.get("day") or i + 1))
        floor0 = w0[0] if (i == 0 and w0) else None
        if i == 0:
            if origin:
                # 到达点：住宿足够近就先去住宿（放行李），否则直接去首站
                if stay and sp.km(stay, fp) <= STAY_NEAR_KM and sp.km(origin, stay) > LOCAL_KM:
                    t = _leg("arrival", oname, origin, sname, stay, meta, f, first_start=fs - 20, depart_floor=floor0)
                    t["via_stay"] = True
                else:
                    t = _leg("arrival", oname, origin, fname, fp, meta, f, first_start=fs, depart_floor=floor0)
        else:
            lp = sp._coord(prev_last) if prev_last else None
            if stay and (meta.get("stays") or sp.km(stay, fp) <= STAY_NEAR_KM):
                t = _leg("daily", sname, stay, fname, fp, meta, f)
                if t["distance_km"] < 0.25 and not meta.get("stays"):
                    t = None
            elif lp and sp.km(lp, fp) > LOCAL_KM:
                t = _leg("intercity", str(prev_last.get("name") or "上一站"), lp, fname, fp, meta, f, first_start=fs)
        dno = int(day.get("day") or i + 1)
        if t:
            day["transit_start"] = t
            if rc.is_comparable(t):   # 用户在「路线对比」里选定过的方案，覆盖里程估算
                rc.apply_choice(plan, dno, "transit_start", t, first_start=fs - (20 if t.get("via_stay") else 0))
                if floor0 is not None and t.get('depart') is None and t.get('minutes') is not None:
                    t['depart'], t['arrive'] = fmt_minutes(floor0), fmt_minutes(floor0 + int(t['minutes']))
        if i == len(itin) - 1 and return_point and last:
            lp2 = sp._coord(last)
            if lp2 and sp.km(lp2, return_point) > 0.3:
                day["transit_end"] = _leg("return", str(last.get("name") or "最后一站"), lp2, return_name, return_point, meta, f,
                                          after_end=_end_minute(last, last in (day.get("meals") or [])))
                if rc.is_comparable(day["transit_end"]):
                    rc.apply_choice(plan, dno, "transit_end", day["transit_end"])
        if i < len(itin) - 1 and end_stay and last:
            day['transit_end'] = _leg('daily', str(last.get('name') or '最后一站'), sp._coord(last), end_sname, end_stay, meta, f,
                                      after_end=_end_minute(last))
        park = meta.get('parking_point') or {}
        pp = _pt(park.get('lat'), park.get('lng'))
        if meta.get('driving_strategy') == 'park_ride' and pp and last:
            pn = clean_origin(park.get('name')) or '停车换乘点'
            drive_meta = {**meta, 'transportation': '自驾'}
            city_meta = {**meta, 'transportation': '公共交通'}
            start_legs = []
            base = origin if i == 0 else stay
            base_name = oname if i == 0 else sname
            if base and sp.km(base, pp) > .05:
                start_legs.append(_leg('arrival' if i == 0 else 'daily', base_name, base, pn, pp, drive_meta, f))
            start_legs.append(_leg('daily', pn, pp, fname, fp, city_meta, f))
            end_legs = [_leg('daily', str(last.get('name') or '最后一站'), sp._coord(last), pn, pp, city_meta, f)]
            end_base = return_point if i == len(itin) - 1 else end_stay
            end_name = return_name if i == len(itin) - 1 else end_sname
            if end_base and sp.km(pp, end_base) > .05:
                end_legs.append(_leg('return' if i == len(itin) - 1 else 'daily', pn, pp, end_name, end_base, drive_meta, f))
            day['transit_start'] = combine_legs(start_legs, 'arrival' if i == 0 else 'daily', first_start=fs)
            day['transit_end'] = combine_legs(end_legs, 'return' if i == len(itin) - 1 else 'daily', after_end=_end_minute(last, last in (day.get('meals') or [])))
        if meta.get('rental'):
            for key, applies in (('transit_start', i == 0), ('transit_end', i == len(itin) - 1)):
                leg = day.get(key)
                if applies and isinstance(leg, dict):
                    leg['minutes'] += 45
                    leg['note'] = (leg.get('note') or '') + '；另含45分钟取车/还车手续'
                    if key == 'transit_start':
                        departure, _ = parse_range(leg.get('depart'))
                        departure = departure if departure is not None else (floor0 if floor0 is not None else max(EARLIEST_DEPART, fs - leg['minutes'] - ARRIVE_BUFFER))
                        if floor0 is not None:
                            departure = max(departure, floor0)
                        arrival = departure + leg['minutes']
                        leg['depart'], leg['arrive'] = fmt_minutes(departure), absolute_time(arrival)
                        leg['late_min'] = max(0, arrival + ARRIVE_BUFFER - fs)
                        if leg['late_min'] > 20:
                            leg['warning'] = '取车与抵达时间超过首站时间，需要顺延游览或提前一天取车'
                    else:
                        departure = _end_minute(last, last in (day.get('meals') or [])) + 30
                        leg['depart'], leg['arrive'] = absolute_time(departure), absolute_time(departure + leg['minutes'])
                        if departure + leg['minutes'] >= 1410:
                            leg['warning'] = '返回和还车手续可能超过午夜，请核实门店营业时间并提前结束游览'
        prev_last = last or prev_last
    plan["transits_v"] = 1


def absolute_time(minutes):
    day, minute = divmod(int(minutes), 1440)
    prefix = '' if day == 0 else '次日 ' if day == 1 else f'+{day}天 '
    return prefix + fmt_minutes(minute)


def combine_legs(legs, kind, first_start=None, after_end=None):
    minutes = sum(x['minutes'] for x in legs) + 20
    out = {'kind': kind, 'from': legs[0]['from'], 'to': legs[-1]['to'], 'legs': legs,
           'mode': 'drive_transit', 'mode_label': '自驾＋停车换乘', 'minutes': minutes,
           'distance_km': round(sum(x['distance_km'] for x in legs), 1),
           'cost': round(sum(x['cost'] for x in legs), 2), 'confidence': 'estimate',
           'intercity': any(x['intercity'] for x in legs), 'comparable': False,
           'note': '含20分钟停车/取车换乘缓冲；路段用时与费用为估算'}
    if first_start is not None:
        depart = max(EARLIEST_DEPART, first_start - minutes - ARRIVE_BUFFER)
        out.update(depart=fmt_minutes(depart), arrive=fmt_minutes(depart + minutes))
        late = depart + minutes + ARRIVE_BUFFER - first_start
        if late > 20:
            out.update(late_min=late, warning='驾车及停车换乘时间不足，首日安排需顺延或提前一天抵达')
    if after_end is not None:
        out['depart'] = fmt_minutes(after_end + 15)
        end = after_end + 15 + minutes
        out['arrive'] = ('次日 ' if end >= 1440 else '') + fmt_minutes(end % 1440)
        if end >= 1410:
            out['warning'] = '取车及返回可能超过午夜，请提前结束游览或调整返程安排'
    return out


def paid_cost(plan: Dict[str, Any]) -> Dict[str, Any]:
    """预算里要额外计入的城际/到达/返程费用（本地的 daily 路段已在逐段交通里算过，不重复）。"""
    total, items = 0.0, []
    for d in plan.get("itinerary") or []:
        if not isinstance(d, dict):
            continue
        for key in ("transit_start", "transit_end"):
            t = d.get(key)
            if isinstance(t, dict) and t.get("kind") in ("arrival", "intercity", "return") and float(t.get("cost") or 0) > 0:
                total += float(t["cost"])
                items.append({"day": d.get("day"), "kind": t["kind"], "mode": t.get("mode"), "label": t.get("mode_label"), "cost": round(float(t["cost"])),
                              "from": (t.get("from") or {}).get("name"), "to": (t.get("to") or {}).get("name"), "intercity": bool(t.get("intercity"))})
    return {"total": total, "items": items}


def snapshot(itinerary: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """给前端同步用：每天的 transit_start / transit_end。"""
    return [{"day": d.get("day"), "transit_start": d.get("transit_start"), "transit_end": d.get("transit_end")}
            for d in itinerary if isinstance(d, dict)]


def copy_transits(src: List[Dict[str, Any]], dst: List[Dict[str, Any]]) -> None:
    """把 src 每天的 transit_* 写到 dst 对应的天（按下标；不动其它字段，避免覆盖并发写入的图片等）。"""
    for s_d, d_d in zip(src or [], dst or []):
        if not isinstance(s_d, dict) or not isinstance(d_d, dict):
            continue
        for k in ("transit_start", "transit_end"):
            if isinstance(s_d.get(k), dict):
                d_d[k] = s_d[k]
            else:
                d_d.pop(k, None)


# ---------------------------------------------------------------- 生成时：按抵达时间顺延第 1 天

LATEST_END = 22 * 60 + 30


def adapt_day1(plan: Dict[str, Any], meta: Dict[str, Any], fares: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """外地出发时，第 1 天的安排要从抵达之后开始：把当天所有时间整体后移，并去掉晚于 22:30 的活动/抵达前的早餐。
    只在「刚生成」时调用（用户之后的手动编辑不再自动改动）。返回一句说明（没有调整返回 None）。"""
    from .itinerary_edit import fmt_range

    build(plan, meta, fares)
    itin = [d for d in (plan.get("itinerary") or []) if isinstance(d, dict)]
    if not itin:
        return None
    t = itin[0].get("transit_start")
    if not isinstance(t, dict) or not t.get("intercity") or int(t.get("late_min") or 0) <= 20:
        return None
    delta = min(6 * 60, ((int(t["late_min"]) + 29) // 30) * 30)
    day = itin[0]
    dropped: List[str] = []

    def shift(items: List[Any], is_meal: bool) -> List[Any]:
        keep = []
        for it in items:
            if not isinstance(it, dict):
                keep.append(it)
                continue
            s, e = parse_range(it.get("time"))
            if s is None:
                keep.append(it)
                continue
            ns, ne = s + delta, (e + delta if e is not None else None)
            if (ne if ne is not None else ns + 60) > LATEST_END or (is_meal and str(it.get("type")) == "breakfast"):
                dropped.append(str(it.get("name") or ""))
                continue
            it["time"] = fmt_range(ns, ne)
            keep.append(it)
        return keep

    acts = shift(day.get("activities") or [], False)
    meals = shift(day.get("meals") or [], True)
    if not acts:  # 一个都排不下就不动
        return None
    day["activities"], day["meals"] = acts, meals
    build(plan, meta, fares)
    h = round(delta / 60, 1)
    tail = "，已移除放不下的：" + "、".join(n for n in dropped if n)[:60] if dropped else ""
    return f"从{(t.get('from') or {}).get('name') or '出发地'}出发要约 {round(int(t['minutes']) / 60, 1)} 小时，Day 1 的安排已整体顺延 {h} 小时{tail}"



def apply_day1_times(src: Dict[str, Any], dst: Dict[str, Any]) -> None:
    """把顺延后的第 1 天时间按名字写回已保存的那一天（保留其它字段，如后台补上的图片；被移除的条目同步移除）。"""
    for key in ("activities", "meals"):
        new = {str(x.get("name")): x for x in (src.get(key) or []) if isinstance(x, dict)}
        kept = []
        for it in dst.get(key) or []:
            if isinstance(it, dict) and str(it.get("name")) in new:
                it["time"] = new[str(it.get("name"))].get("time", it.get("time"))
                kept.append(it)
        dst[key] = kept


def present_transport(payload):
    """Present legacy transport assumptions honestly without changing saved activities."""
    import copy
    meta=payload.get('trip_meta') or {};travelers=int(meta.get('travelers') or 1)
    legs=[t for d in payload.get('itinerary') or [] for k in ('transit_start','transit_end') if isinstance((t:=d.get(k)),dict)]
    ground=meta.get('longhaul_mode','ground')=='ground' and not any(x in str(meta.get('transportation') or '') for x in ('飞机','航班','航空'))
    projection=ground and any(t.get('mode')=='flight' and not t.get('route_choice') for t in legs)
    mismatch=any((ch:=t.get('route_choice') or {}).get('kind')=='transit' and int(ch.get('passengers') or 1)!=travelers for t in legs)
    if not projection and not mismatch:return
    payload['itinerary']=copy.deepcopy(payload['itinerary'])
    warnings=list(payload.get('warnings') or [])
    if projection:
        build(payload,meta)
        payload['transport_projection']=True
        if payload.get('review'):
            payload['review']=copy.deepcopy(payload['review'])
            payload['review']['projection_note']='交通显示已按当前偏好修正，原评审尚未重新核对；请先处理跨天交通再复核。'
        warnings.append('已按保存的地面公共交通偏好修正旧版自动飞机假设；跨天交通仍需确认，活动未自动重排。')
    if mismatch:
        for day in payload['itinerary']:
            for key in ('transit_start','transit_end'):
                t=day.get(key)
                if not isinstance(t,dict):continue
                ch=t.get('route_choice') or {};n=int(ch.get('passengers') or 1)
                if ch.get('kind')=='transit' and n!=travelers:
                    t['party_mismatch']=True
                    t['note']=(t.get('note') or '')+f'；该方案按{n}人查询，当前旅途{travelers}人，预算按人数换算参考，请重新对比。'
        warnings.append('已选交通方案的查询人数与旅途人数不一致，请按当前同行人数重新对比。')
    payload['warnings']=list(dict.fromkeys(warnings))
