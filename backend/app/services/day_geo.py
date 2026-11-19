"""行程地理合理性校验：每天的点应当落在同一片区域，否则标出来而不是悄悄交付。

背景：候选池可能混入别的城市（例如搜索词命中同名/连锁店），composer 只负责“打包进天”，不做地理验证。
这里用**纯代码**兜底：
  1. 以当天活动坐标的中位数为中心，剔除超过 max_km 的离群点（保留至少 2 个）；
  2. 去掉占位餐饮（“breakfast 安排”之类）和坐标缺失/离群的餐饮；
  3. 对仍然跨度过大 / 点太少的天、以及全程跨城的行程，生成**真实的 warnings**。
"""

from __future__ import annotations

import math
import re
from typing import Any, Dict, List, Optional, Tuple

DAY_RADIUS_KM = 30.0       # 同一天内允许离当天中心的最大距离
TRIP_SPREAD_KM = 120.0     # 各天中心之间超过它 → 判定为跨城行程
MIN_ACTIVITIES = 2

_PLACEHOLDER = re.compile(r"^(breakfast|lunch|dinner|早餐|午餐|晚餐)\s*(安排)?$", re.I)


def _coord(item: Dict[str, Any]) -> Optional[Tuple[float, float]]:
    try:
        lat = float(item.get("latitude") if item.get("latitude") is not None else item.get("lat"))
        lng = float(item.get("longitude") if item.get("longitude") is not None else item.get("lng"))
    except (TypeError, ValueError):
        return None
    if abs(lat) < 1e-6 and abs(lng) < 1e-6:
        return None
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return None
    return lat, lng


def haversine_km(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    r = 6371.0
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dphi, dl = p2 - p1, math.radians(b[1] - a[1])
    h = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(h)))


def _median(vals: List[float]) -> float:
    s = sorted(vals)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def center_of(points: List[Tuple[float, float]]) -> Optional[Tuple[float, float]]:
    if not points:
        return None
    return _median([p[0] for p in points]), _median([p[1] for p in points])


def is_placeholder_meal(m: Dict[str, Any]) -> bool:
    name = str(m.get("name") or "").strip()
    return not name or bool(_PLACEHOLDER.match(name))


def sanitize_itinerary(itinerary: List[Dict[str, Any]], *, radius_km: float = DAY_RADIUS_KM) -> Tuple[List[Dict[str, Any]], List[str], Dict[str, Any]]:
    """返回 (清洗后的行程, warnings, 统计)。不修改入参。"""
    warnings: List[str] = []
    stats = {"dropped_activities": 0, "dropped_meals": 0, "flagged_days": [], "centers": []}
    out: List[Dict[str, Any]] = []
    centers: List[Tuple[int, Tuple[float, float]]] = []

    for day in itinerary:
        dno = int(day.get("day") or len(out) + 1)
        acts = [a for a in (day.get("activities") or []) if isinstance(a, dict)]
        meals = [m for m in (day.get("meals") or []) if isinstance(m, dict)]
        pts = [c for c in (_coord(a) for a in acts) if c]
        ctr = center_of(pts)
        kept_acts = acts
        if ctr and len(pts) >= 3:
            far = [a for a in acts if (_coord(a) and haversine_km(_coord(a), ctr) > radius_km)]
            near = [a for a in acts if a not in far]
            if far and len(near) >= MIN_ACTIVITIES:
                kept_acts = near
                stats["dropped_activities"] += len(far)
                names = "、".join(str(a.get("name") or "") for a in far[:3])
                warnings.append(f"Day {dno}：已移除 {len(far)} 个距当天区域过远的地点（{names}）")
            elif far:
                stats["flagged_days"].append(dno)
                warnings.append(f"Day {dno}：景点分布在相距较远的区域，建议用“调整这一站”换成同一片区的地点")
            pts = [c for c in (_coord(a) for a in kept_acts) if c]
            ctr = center_of(pts)

        kept_meals: List[Dict[str, Any]] = []
        for m in meals:
            if is_placeholder_meal(m):
                stats["dropped_meals"] += 1
                continue
            mc = _coord(m)
            if ctr and mc and haversine_km(mc, ctr) > radius_km:
                stats["dropped_meals"] += 1
                continue
            kept_meals.append(m)
        if len(meals) != len(kept_meals) and len(kept_meals) < len(meals):
            miss = len(meals) - len(kept_meals)
            warnings.append(f"Day {dno}：有 {miss} 顿餐食暂未匹配到合适的就近餐厅，已留出空档，可点“找点乐子”就近挑选或手动添加")

        if ctr:
            centers.append((dno, ctr))
            stats["centers"].append({"day": dno, "lat": round(ctr[0], 4), "lng": round(ctr[1], 4)})
        out.append({**day, "activities": kept_acts, "meals": kept_meals})

    # 跨城检测：任意两天中心相距过远
    if len(centers) >= 2:
        far_pair = max(
            ((a, b, haversine_km(a[1], b[1])) for i, a in enumerate(centers) for b in centers[i + 1:]),
            key=lambda t: t[2],
        )
        if far_pair[2] > TRIP_SPREAD_KM:
            warnings.insert(0, f"行程在 Day {far_pair[0][0]} 与 Day {far_pair[1][0]} 之间跨度约 {int(far_pair[2])} km，已不是同一座城市；"
                               "建议缩小到一座城市重新规划")
            stats["spread_km"] = int(far_pair[2])
    return out, warnings, stats


def filter_attractions(attractions: List[Dict[str, Any]], itinerary: List[Dict[str, Any]], *, radius_km: float = TRIP_SPREAD_KM / 2) -> List[Dict[str, Any]]:
    """顶层 attractions 去掉离所有天中心都很远的点（保证地图/地点数不被离群点污染）。"""
    ctrs = []
    for day in itinerary:
        c = center_of([p for p in (_coord(a) for a in day.get("activities") or []) if p])
        if c:
            ctrs.append(c)
    if not ctrs:
        return attractions
    out = []
    for a in attractions:
        c = _coord(a)
        if c is None or min(haversine_km(c, x) for x in ctrs) <= radius_km:
            out.append(a)
    return out

