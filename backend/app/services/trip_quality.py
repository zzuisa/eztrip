"""行程质量评分（确定性、不调用模型）：评测集与反馈分析共用。

输入：已保存的行程 payload（itinerary / attractions / warnings / trip_meta）。
输出：{"score": 0-100, "metrics": {...}, "issues": [{"code","day","text","weight"}]}
用途：
  1. 评测集：对一批真实/固定行程跑同一把尺子，改了规划逻辑后对比分数有没有退步（python -m app.evals）；
  2. 反馈分析：用户点“不满意”时，把主观反馈和客观问题放在一起看。
这里只度量“代码能确定的问题”，不评价“好不好玩”。
"""

from __future__ import annotations

import datetime as _dt
from typing import Any, Dict, List, Optional

from ..agents import polish
from . import opening_hours as oh
from .day_geo import DAY_RADIUS_KM, _coord, center_of, haversine_km
from .itinerary_utils import _ensure_list

# 各类问题的扣分（每处）与单类上限
_RULES = {
    "closed_day": (8, 24),        # 排在闭馆日 / 营业时间之外
    "overlap": (6, 18),           # 同一天时间重叠
    "meal_window": (3, 12),       # 早/午/晚餐落在不合理时段
    "meal_missing": (3, 12),      # 有景点的一天缺午餐或晚餐
    "no_coord": (2, 10),          # 缺坐标（地图画不出来）
    "far_point": (5, 15),         # 离当天中心过远
    "long_hop": (3, 9),           # 相邻两站直线距离过大
    "empty_day": (15, 30),
    "overload": (4, 12),          # 一天景点过多
    "late_end": (3, 9),           # 活动晚于 23:00 或早于 6:30
    "dup_place": (4, 12),         # 同一地点/餐厅在多天重复
    "no_image": (1, 8),
    "warning": (2, 10),           # 系统已提示的问题
}
LONG_HOP_KM = 15.0
MAX_ACTIVITIES = 6


def _start_date(payload: Dict[str, Any]) -> Optional[_dt.date]:
    meta = payload.get("trip_meta") if isinstance(payload.get("trip_meta"), dict) else {}
    s = str(meta.get("start_date") or "")[:10]
    try:
        return _dt.date.fromisoformat(s)
    except ValueError:
        return None


def score_trip(payload: Dict[str, Any]) -> Dict[str, Any]:
    issues: List[Dict[str, Any]] = []

    def add(code: str, day: int, text: str) -> None:
        issues.append({"code": code, "day": day, "text": text, "weight": _RULES[code][0]})

    days = [d for d in _ensure_list(payload.get("itinerary")) if isinstance(d, dict)]
    base = _start_date(payload)
    hours = {str(a.get("name") or "").strip().lower(): a.get("hours")
             for a in _ensure_list(payload.get("attractions")) if isinstance(a, dict) and a.get("hours")}
    seen_place: Dict[str, int] = {}
    n_acts = n_meals = n_img = n_coord = n_checked = 0

    for k, day in enumerate(days):
        dn = int(day.get("day") or (k + 1))
        acts = [a for a in _ensure_list(day.get("activities")) if isinstance(a, dict)]
        meals = [m for m in _ensure_list(day.get("meals")) if isinstance(m, dict)]
        if not acts:
            add("empty_day", dn, "Day %d 没有景点" % dn)
        if len(acts) > MAX_ACTIVITIES:
            add("overload", dn, "Day %d 安排了 %d 个景点" % (dn, len(acts)))

        ranges: List[Any] = []
        for it, kind in [(a, "activity") for a in acts] + [(m, "meal") for m in meals]:
            n_acts += kind == "activity"
            n_meals += kind == "meal"
            n_img += bool(it.get("image_url") or it.get("photo_url"))
            if _coord(it):
                n_coord += 1
            else:
                add("no_coord", dn, "Day %d「%s」没有坐标" % (dn, it.get("name")))
            r = polish.parse_range(it.get("time"))
            if r:
                ranges.append((r, str(it.get("name") or "")))
                if r[0] < 6 * 60 + 30 or r[1] > 23 * 60:
                    add("late_end", dn, "Day %d「%s」时间 %s 过早或过晚" % (dn, it.get("name"), it.get("time")))
            key = str(it.get("name") or "").strip().lower()
            if key:
                if key in seen_place and seen_place[key] != dn:
                    add("dup_place", dn, "「%s」在 Day %d 和 Day %d 重复" % (it.get("name"), seen_place[key], dn))
                seen_place.setdefault(key, dn)

        ranges.sort()
        for (r1, n1), (r2, n2) in zip(ranges, ranges[1:]):
            if r2[0] < r1[1]:
                add("overlap", dn, "Day %d「%s」与「%s」时间重叠" % (dn, n1, n2))

        types = {str(m.get("type") or "") for m in meals}
        if acts:
            for t, label in (("lunch", "午餐"), ("dinner", "晚餐")):
                if t not in types:
                    add("meal_missing", dn, "Day %d 缺少%s" % (dn, label))
        for m in meals:
            w = polish._WINDOW.get(str(m.get("type") or ""))
            r = polish.parse_range(m.get("time"))
            if w and r and not (w[0][0] <= r[0] <= w[0][1]):
                add("meal_window", dn, "Day %d%s 开始于 %s" % (dn, m.get("name"), polish.fmt_range(*r).split("-")[0]))

        pts = [(a, _coord(a)) for a in acts]
        coords = [c for _, c in pts if c]
        ctr = center_of(coords)
        if ctr:
            for a, c in pts:
                if c and haversine_km(c, ctr) > DAY_RADIUS_KM:
                    add("far_point", dn, "Day %d「%s」离当天中心 %.0f km" % (dn, a.get("name"), haversine_km(c, ctr)))
        order = sorted((a for a in acts if _coord(a) and polish.parse_range(a.get("time"))), key=lambda a: polish.parse_range(a.get("time"))[0])
        for a, b in zip(order, order[1:]):
            d = haversine_km(_coord(a), _coord(b))
            if d > LONG_HOP_KM:
                add("long_hop", dn, "Day %d「%s」→「%s」直线 %.0f km" % (dn, a.get("name"), b.get("name"), d))

        if base is not None:
            dow = (base + _dt.timedelta(days=dn - 1)).weekday()
            for a in acts:
                h = hours.get(str(a.get("name") or "").strip().lower())
                r = polish.parse_range(a.get("time"))
                if not oh.valid(h) or not r:
                    continue
                n_checked += 1
                st, _ = oh.check(h, dow, r[0], r[1])
                if st in ("closed", "outside"):
                    add("closed_day", dn, "Day %d「%s」%s" % (dn, a.get("name"), "周%s不营业" % oh.WEEK[dow] if st == "closed" else "不在营业时段内"))

    for w in _ensure_list(payload.get("warnings")):
        add("warning", 0, str(w))

    per: Dict[str, int] = {}
    for i in issues:
        per[i["code"]] = per.get(i["code"], 0) + i["weight"]
    no_img = max(0, n_acts + n_meals - n_img)
    if no_img:
        per["no_image"] = no_img * _RULES["no_image"][0]
        issues.append({"code": "no_image", "day": 0, "text": "%d 个地点没有图片" % no_img, "weight": per["no_image"]})
    penalty = sum(min(v, _RULES[c][1]) for c, v in per.items())
    total = n_acts + n_meals
    return {
        "score": max(0, 100 - penalty),
        "metrics": {
            "days": len(days), "activities": n_acts, "meals": n_meals,
            "image_rate": round(n_img / total, 3) if total else 0.0,
            "coord_rate": round(n_coord / total, 3) if total else 0.0,
            "hours_checked": n_checked,
            "dated": base is not None,
        },
        "issues": issues,
    }

