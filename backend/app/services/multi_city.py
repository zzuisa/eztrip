"""多城市串联：把每一站各自生成的行程拼成一份连续的行程（天数顺延、标注所在城市）。

每一站仍走原来的单城市生成流程（质量与限流不变）；这里只负责规范化请求和合并结果。
站与站之间的交通（Day 1 的出发、换城那天的第一程）由 transit_plan 按坐标统一计算。
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional

from .origin import clean_origin

MAX_STOPS = 4
MAX_DAYS = 15


def _get(s: Any, k: str) -> Any:
    return s.get(k) if isinstance(s, dict) else getattr(s, k, None)


def normalize_segments(segments: Optional[List[Any]], total_days: int = 0) -> List[Dict[str, Any]]:
    """清洗 segments：去空、相邻重复城市合并、限制站数与总天数。不足 2 站返回空列表（按单城市处理）。"""
    out: List[Dict[str, Any]] = []
    for s in segments or []:
        city = clean_origin(_get(s, "city"))[:30]
        try:
            days = max(1, min(MAX_DAYS, int(_get(s, "days"))))
        except (TypeError, ValueError):
            days = 2
        if not city:
            continue
        if out and out[-1]["city"].lower() == city.lower():
            out[-1]["days"] += days
        else:
            out.append({"city": city, "days": days})
    out = out[:MAX_STOPS]
    over = sum(s["days"] for s in out) - MAX_DAYS
    while over > 0:  # 总天数超限：从天数最多的站里减
        big = max(out, key=lambda x: x["days"])
        if big["days"] <= 1:
            break
        big["days"] -= 1
        over -= 1
    return out if len(out) >= 2 else []


def merge(results: List[Dict[str, Any]], segs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """results[i] 是第 i 站的单城市行程 payload。返回合并后的 payload。"""
    itinerary: List[Dict[str, Any]] = []
    attractions: List[Dict[str, Any]] = []
    tips: List[str] = []
    warnings: List[str] = []
    seen = set()
    meta_segments = []
    offset = 0
    for i, (seg, data) in enumerate(zip(segs, results)):
        days = [d for d in (data.get("itinerary") or []) if isinstance(d, dict)]
        meta_segments.append({"city": seg["city"], "days": seg["days"], "start_day": offset + 1})
        for j, d in enumerate(days):
            nd = copy.deepcopy(d)
            nd["day"] = offset + j + 1
            nd["city"] = seg["city"]
            nd["segment"] = i
            itinerary.append(nd)
        for a in data.get("attractions") or []:
            key = str((a or {}).get("name") or "").strip().lower()
            if key and key not in seen:
                seen.add(key)
                attractions.append(a)
        tips += [t for t in (data.get("tips") or []) if t not in tips]
        warnings += [("【%s】" % seg["city"]) + w for w in (data.get("warnings") or []) if isinstance(w, str)]
        offset += max(len(days), seg["days"])
    weather_days = [d for data in results for d in (data.get('weather_info') or [])]
    reports = [data['weather'] for data in results if data.get('weather')]
    base = dict(results[0]) if results else {}
    if reports:
        base['weather'] = {**reports[0], 'location': ' → '.join(s['city'] for s in segs), 'days': weather_days,
                           'segments': reports, 'status': ('date_required' if all(r.get('status') == 'date_required' for r in reports) else 'available' if all(r.get('status') == 'available' for r in reports) else 'partial')}
        base['weather_info'] = weather_days
    reports_xhs=[d.get('xhs_research',{}) for d in results]
    base['xhs_research']={'segments':reports_xhs,'selected_notes':list({n['id']:n for r in reports_xhs for n in r.get('selected_notes',[])}.values()),'used_note_ids':sorted({n for r in reports_xhs for n in r.get('used_note_ids',[])})}
    base.update({
        "location": " → ".join(s["city"] for s in segs),
        "days": len(itinerary),
        "attractions": attractions,
        "itinerary": itinerary,
        "tips": tips,
        "warnings": warnings,
        "segments": meta_segments,
        "total_budget": {"transport": 0, "tickets": 0, "food": 0, "total": 0, "currency": "EUR"},
    })
    for k in ("stay", "story", "trip_meta", "request_preferences", "result_id"):
        base.pop(k, None)
    return base
