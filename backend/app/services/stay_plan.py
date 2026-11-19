"""预选住宿进入规划：清洗输入、生成给 LLM 的提示片段、按住宿重排每天的行程顺序（纯代码，不耗模型）。

住宿来自用户输入/地图选点，是不可信文本：与出发地同样做清洗与长度限制。
"""

from __future__ import annotations

import copy
import itertools
import math
from typing import Any, Dict, List, Optional, Tuple

from .itinerary_edit import item_start, parse_range
from .origin import clean_origin

ROAD_FACTOR = 1.3  # 直线距离 → 实际路程的经验系数


def clean_stay(name: Optional[str]) -> str:
    return clean_origin(name)


def stay_point(meta: Optional[Dict[str, Any]]) -> Optional[Tuple[float, float]]:
    m = meta or {}
    try:
        lat, lng = float(m.get("stay_lat")), float(m.get("stay_lng"))
    except (TypeError, ValueError):
        return None
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return None
    return lat, lng


def stay_sentence(name: Optional[str], lat: Optional[float] = None, lng: Optional[float] = None) -> str:
    """流水线模式：追加到偏好后的一句话（无住宿返回空串）。"""
    n = clean_stay(name)
    if not n:
        return ""
    where = f"（坐标约 {lat:.4f},{lng:.4f}）" if lat is not None and lng is not None else ""
    return (
        f"；旅行者已选定住宿「{n}」{where}：请围绕住宿安排每一天——按景点离住宿的远近把相邻景点聚到同一天，"
        "每天的第一站尽量顺路、最后一站收在回住宿方便的位置，晚餐优先选在住宿所在片区；"
        "第 1 天抵达后先到住宿寄存行李，最后一天预留退房时间；不要让一天里来回穿越城市"
    )


def stay_block(name: Optional[str], day: int, days: int) -> str:
    """Agent 模式单天编排提示块。"""
    n = clean_stay(name)
    if not n:
        return ""
    lines = [f"旅行者已选定住宿：「{n}」。这一天从住宿出发、最终回到住宿：第一个活动选顺路的，最后一个活动之后要方便返回住宿，晚餐优先住宿片区。"]
    if day == 1:
        lines.append("第 1 天抵达后先到住宿寄存行李/办理入住，再开始游览。")
    if day == days and days > 1:
        lines.append("最后一天要退房：早上先处理行李，景点选离住宿或交通枢纽近的。")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- 距离与重排


def km(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    h = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(b[1] - a[1]) / 2) ** 2
    return 6371.0 * 2 * math.atan2(math.sqrt(h), math.sqrt(1 - h))


def road_km(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    return km(a, b) * ROAD_FACTOR


def _coord(it: Dict[str, Any]) -> Optional[Tuple[float, float]]:
    try:
        lat, lng = float(it.get("latitude")), float(it.get("longitude"))
    except (TypeError, ValueError):
        return None
    return (lat, lng) if (lat or lng) and -90 <= lat <= 90 and -180 <= lng <= 180 else None


def day_points(day: Dict[str, Any]) -> List[Tuple[float, float]]:
    """一天里按开始时间排序的所有带坐标的条目（景点+餐饮）。"""
    rows = []
    for i, a in enumerate(day.get("activities") or []):
        if isinstance(a, dict) and _coord(a):
            rows.append((item_start(a, False), 0, i, _coord(a)))
    for i, m in enumerate(day.get("meals") or []):
        if isinstance(m, dict) and _coord(m):
            rows.append((item_start(m, True), 1, i, _coord(m)))
    rows.sort(key=lambda r: (r[0], r[1], r[2]))
    return [r[3] for r in rows]


def path_km(points: List[Tuple[float, float]], stay: Optional[Tuple[float, float]]) -> float:
    seq = ([stay] if stay else []) + points + ([stay] if stay and points else [])
    return sum(road_km(seq[i], seq[i + 1]) for i in range(len(seq) - 1))


def _best_order(pts: List[Tuple[float, float]], stay: Tuple[float, float]) -> List[int]:
    n = len(pts)
    if n <= 1:
        return list(range(n))

    def cost(order) -> float:
        seq = [stay] + [pts[i] for i in order] + [stay]
        return sum(km(seq[i], seq[i + 1]) for i in range(len(seq) - 1))

    if n <= 7:
        return list(min(itertools.permutations(range(n)), key=cost))
    # 最近邻 + 2-opt
    left, order, cur = set(range(n)), [], stay
    while left:
        nx = min(left, key=lambda i: km(cur, pts[i]))
        order.append(nx)
        left.discard(nx)
        cur = pts[nx]
    improved = True
    while improved:
        improved = False
        for i in range(n - 1):
            for j in range(i + 1, n):
                cand = order[:i] + order[i:j + 1][::-1] + order[j + 1:]
                if cost(cand) + 1e-9 < cost(order):
                    order, improved = cand, True
    return order


def reorder_day(day: Dict[str, Any], stay: Tuple[float, float]) -> Dict[str, Any]:
    """只调整景点顺序（地点不增不减）：让「住宿→景点…→住宿」的路程最短；时间段按位置沿用，餐饮保持不动。
    返回 {changed, before_km, after_km}。仅当带坐标的景点 ≥3 个且确实缩短 ≥8% 时才改动。"""
    acts = [a for a in (day.get("activities") or []) if isinstance(a, dict)]
    idxs = [i for i, a in enumerate(day.get("activities") or []) if isinstance(a, dict) and _coord(a)]
    if len(idxs) < 3:
        return {"changed": False, "before_km": 0.0, "after_km": 0.0}
    order_t = sorted(idxs, key=lambda i: (item_start(day["activities"][i], False), i))
    pts = [_coord(day["activities"][i]) for i in order_t]
    before = path_km(pts, stay)
    best = _best_order(pts, stay)
    new_pts = [pts[i] for i in best]
    after = path_km(new_pts, stay)
    if best == list(range(len(pts))) or after > before * 0.92:
        return {"changed": False, "before_km": round(before, 1), "after_km": round(before, 1)}
    slots = [day["activities"][i].get("time") for i in order_t]
    new_items = [copy.deepcopy(day["activities"][order_t[b]]) for b in best]
    for pos, it in enumerate(new_items):
        if slots[pos]:
            it["time"] = slots[pos]
    for pos, i in enumerate(order_t):
        day["activities"][i] = new_items[pos]
    # 让数组顺序与时间顺序一致
    day["activities"].sort(key=lambda a: item_start(a, False) if isinstance(a, dict) else 0)
    del acts
    return {"changed": True, "before_km": round(before, 1), "after_km": round(after, 1)}


def reorder_itinerary(itinerary: List[Dict[str, Any]], stay: Tuple[float, float]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    new = copy.deepcopy(itinerary)
    report = []
    for d in new:
        pts = day_points(d)
        if pts and km(stay, pts[0]) > 40.0:  # 多城市行程里属于别的城市的天，不按这个住宿重排
            continue
        r = reorder_day(d, stay)
        if r["changed"]:
            report.append({"day": d.get("day"), **r})
    return new, report
