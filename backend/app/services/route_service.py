"""真实路径服务：相邻景点之间用 Mapbox Directions 取步行/驾车路线几何，磁盘缓存；失败降级为直线（不缓存）。"""

from __future__ import annotations

import hashlib
import json
import math
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx

from ..config import get_settings

WALK_MAX_KM = 1.6  # 直线距离不超过它，auto 选步行
MAX_POINTS = 220
CACHE_TTL = 60 * 24 * 3600
NEG_TTL = 300.0


def haversine_m(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 6371000.0 * 2 * math.atan2(math.sqrt(h), math.sqrt(1 - h))


def _perp(p: List[float], a: List[float], b: List[float]) -> float:
    # 平面近似（经度按纬度缩放），用于 Douglas-Peucker 的点到线段距离
    k = math.cos(math.radians((a[1] + b[1]) / 2))
    ax, ay, bx, by, px, py = a[0] * k, a[1], b[0] * k, b[1], p[0] * k, p[1]
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def simplify(pts: List[List[float]], max_points: int = MAX_POINTS) -> List[List[float]]:
    """迭代式 Douglas-Peucker，逐步放宽容差直到点数 ≤ max_points（始终保留首尾）。"""
    if len(pts) <= max_points:
        return pts
    tol = 1e-6
    out = pts
    while len(out) > max_points and tol < 1:
        keep = [False] * len(pts)
        keep[0] = keep[-1] = True
        stack = [(0, len(pts) - 1)]
        while stack:
            s, e = stack.pop()
            dmax, idx = 0.0, -1
            for i in range(s + 1, e):
                d = _perp(pts[i], pts[s], pts[e])
                if d > dmax:
                    dmax, idx = d, i
            if idx >= 0 and dmax > tol:
                keep[idx] = True
                stack += [(s, idx), (idx, e)]
        out = [p for p, k in zip(pts, keep) if k]
        tol *= 2
    return out


def pick_mode(a: Tuple[float, float], b: Tuple[float, float], mode: str = "auto") -> str:
    if mode in ("walking", "driving", "transit"):
        return mode
    return "walking" if haversine_m(a, b) / 1000 <= WALK_MAX_KM else "driving"


def straight_leg(a: Tuple[float, float], b: Tuple[float, float], mode: str) -> Dict[str, Any]:
    d = haversine_m(a, b)
    speed = 1.3 if mode == "walking" else 11.0  # m/s，粗估
    return {
        "mode": mode,
        "distance_m": int(d),
        "duration_s": int(d / speed),
        "geometry": [[round(a[1], 5), round(a[0], 5)], [round(b[1], 5), round(b[0], 5)]],
        "provider": "straight",
    }


class RouteService:
    def __init__(self, cache_dir: Optional[Path] = None, token: Optional[str] = None) -> None:
        self.dir = cache_dir or Path(__file__).resolve().parents[2] / "storage" / "route_cache"
        self.dir.mkdir(parents=True, exist_ok=True)
        self._token = token
        self._neg: Dict[str, float] = {}
        self._lock = threading.Lock()

    @property
    def token(self) -> str:
        return self._token if self._token is not None else (get_settings().mapbox_access_token or "")

    @staticmethod
    def key(a: Tuple[float, float], b: Tuple[float, float], mode: str) -> str:
        raw = f"{mode}|{a[0]:.5f},{a[1]:.5f}|{b[0]:.5f},{b[1]:.5f}"
        return hashlib.sha1(raw.encode()).hexdigest()

    def _path(self, key: str) -> Path:
        return self.dir / f"{key}.json"

    def cached(self, key: str) -> Optional[Dict[str, Any]]:
        p = self._path(key)
        try:
            if p.exists() and time.time() - p.stat().st_mtime < CACHE_TTL:
                return json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return None
        return None

    def _fetch(self, a: Tuple[float, float], b: Tuple[float, float], mode: str) -> Optional[Dict[str, Any]]:
        tok = self.token
        if not tok:
            return None
        url = f"https://api.mapbox.com/directions/v5/mapbox/{mode}/{a[1]:.6f},{a[0]:.6f};{b[1]:.6f},{b[0]:.6f}"
        r = httpx.get(url, params={"geometries": "geojson", "overview": "full", "access_token": tok}, timeout=8.0)
        if r.status_code != 200:
            print(f"[route] mapbox {r.status_code} {mode}")
            return None
        routes = (r.json().get("routes") or [])
        if not routes:
            return None
        rt = routes[0]
        coords = (rt.get("geometry") or {}).get("coordinates") or []
        if len(coords) < 2:
            return None
        coords = simplify([[round(c[0], 5), round(c[1], 5)] for c in coords])
        return {
            "mode": mode,
            "distance_m": int(rt.get("distance") or 0),
            "duration_s": int(rt.get("duration") or 0),
            "geometry": coords,
            "provider": "mapbox",
        }

    def leg(self, a: Tuple[float, float], b: Tuple[float, float], mode: str = "auto", allow_remote: bool = True) -> Dict[str, Any]:
        m = pick_mode(a, b, mode)
        if m == 'transit':
            return straight_leg(a, b, m)  # Indicative connection, never label a driving road as a transit route.
        if haversine_m(a, b) < 15:
            return straight_leg(a, b, m)
        key = self.key(a, b, m)
        hit = self.cached(key)
        if hit:
            return hit
        now = time.time()
        with self._lock:
            if self._neg.get(key, 0) > now:
                return straight_leg(a, b, m)
        if not allow_remote:
            return straight_leg(a, b, m)
        try:
            res = self._fetch(a, b, m)
        except Exception as e:  # noqa: BLE001
            print(f"[route] fetch failed {type(e).__name__}: {e}")
            res = None
        if res:
            try:
                tmp = self._path(key).with_suffix(".tmp")
                tmp.write_text(json.dumps(res), encoding="utf-8")
                tmp.replace(self._path(key))
            except Exception:  # noqa: BLE001
                pass
            return res
        with self._lock:
            self._neg[key] = now + NEG_TTL
            if len(self._neg) > 2000:
                self._neg = {k: v for k, v in self._neg.items() if v > now}
        return straight_leg(a, b, m)


_svc: Optional[RouteService] = None


def get_route_service() -> RouteService:
    global _svc
    if _svc is None:
        _svc = RouteService()
    return _svc

