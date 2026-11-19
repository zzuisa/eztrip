"""德铁直达车次搜索（MCP Timetables）：站点解析 + 多小时窗口 + 到达时刻 + 实时晚点/取消。"""

from __future__ import annotations

import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple

from ...models.schemas import DbStation
from .debug import db_log
from .station_resolver import DbStationResolver
from .trip_search import (
    Stop,
    build_trip,
    find_direct,
    index_by_key,
    is_regional,
    name_keys,
    norm_name,
    parse_stops,
)

PLANNED_TTL = 600.0
CURRENT_TTL = 45.0
MAX_ORIGIN_HOURS = 6
MAX_DEST_HOURS = 8


class DbUnavailable(RuntimeError):
    """德铁数据源（MCP）不可用 —— 与“没有车次”区分开，不能静默返回空列表。"""


class StationNotFound(LookupError):
    def __init__(self, role: str, query: str):
        super().__init__(f"{role}「{query}」没有匹配的德国铁路车站")
        self.role, self.query = role, query


class _NoData(Exception):
    pass


class OutOfWindow(LookupError):
    """DB Timetables 只发布“当前时刻起约 18 小时内”的计划数据，更远/更早的日期是 404（不是服务故障）。"""

    def __init__(self, start: datetime):
        super().__init__(
            f"德铁官方时刻表接口只提供当前时刻起约 18 小时内的计划车次，查不到 {start:%Y-%m-%d %H:%M} 的车次"
        )
        self.start = start


def _is_404(e: BaseException) -> bool:
    return "404" in str(e) and "Not Found" in str(e)


@dataclass
class Place:
    name: str
    evas: List[str]
    query: str


@dataclass
class SearchResult:
    trips: List[Dict[str, Any]] = field(default_factory=list)
    origin: Optional[Place] = None
    destination: Optional[Place] = None
    notes: List[str] = field(default_factory=list)
    filtered_out: int = 0
    regional_only: bool = True


def _clean_display(name: str) -> str:
    return re.sub(r"\s*\((tief|S-Bahn)\)\s*", " ", name or "", flags=re.I).strip()


class DbTripSearcher:
    def __init__(self, call_tool: Callable[[str, Dict[str, Any]], Any], resolver: DbStationResolver) -> None:
        self._call = call_tool
        self._resolver = resolver
        self._cache: Dict[Tuple, Tuple[float, Any]] = {}
        self._lock = threading.Lock()

    # ---------- 缓存 + 调用 ----------
    def _cached(self, key: Tuple, ttl: float, fn: Callable[[], Any]) -> Any:
        now = time.time()
        with self._lock:
            hit = self._cache.get(key)
            if hit and now - hit[0] < ttl:
                return hit[1]
            if len(self._cache) > 400:
                self._cache = {k: v for k, v in self._cache.items() if now - v[0] < ttl}
        val = fn()
        with self._lock:
            self._cache[key] = (time.time(), val)
        return val

    def _planned(self, eva: str, day: datetime, hour: int) -> List[Stop]:
        date, hh = day.strftime("%y%m%d"), f"{hour:02d}"

        def go() -> List[Stop]:
            raw = self._call("getPlannedTimetable", {"evaNo": eva, "date": date, "hour": hh})
            return parse_stops(raw)

        def safe() -> List[Stop]:
            try:
                return go()
            except RuntimeError as e:
                if _is_404(e):
                    raise _NoData() from e
                raise

        return self._cached(("p", eva, date, hh), PLANNED_TTL, safe)

    def _current(self, eva: str) -> Dict[str, Stop]:
        def go() -> Dict[str, Stop]:
            raw = self._call("getCurrentTimetable", {"evaNo": eva})
            return index_by_key(parse_stops(raw))

        try:
            return self._cached(("c", eva), CURRENT_TTL, go)
        except Exception as e:  # noqa: BLE001  实时信息缺失不影响基础结果
            print(f"[db] current timetable failed eva={eva}: {type(e).__name__}: {e}")
            return {}

    # ---------- 站点 ----------
    def resolve(self, query: str, role: str) -> Place:
        try:
            cands = self._resolver.search_candidates("findStations", query)
        except Exception as e:  # noqa: BLE001
            raise DbUnavailable(f"站点查询失败：{type(e).__name__}: {e}") from e
        if not cands:
            raise StationNotFound(role, query)
        best = self._pick(cands, query)
        evas = [best.id]
        if re.search(r"\(tief\)", best.name, re.I):
            # Hbf (tief) 的地面站 EVA 在 meta 里（如 8000105），主站台的车次挂在它上面
            for alt in best.alt_ids:
                if re.fullmatch(r"8000\d{3}", alt) and alt not in evas:
                    evas.insert(0, alt)
        return Place(name=_clean_display(best.name), evas=evas[:2], query=query)

    @staticmethod
    def _pick(cands: List[DbStation], query: str) -> DbStation:
        qk = name_keys(query)
        qtokens = set(norm_name(query).split())

        def score(s: DbStation) -> int:
            keys = name_keys(s.name)
            sc = 0
            if qk & keys:
                sc += 100
            elif qtokens and qtokens <= set(norm_name(s.name).split()):
                sc += 30
            if "hbf" in norm_name(s.name).split():
                sc += 10
            return sc

        return max(cands, key=score)  # max 取首个最大值：保持 MCP 返回顺序

    # ---------- 搜索 ----------
    def search(
        self,
        origin: str,
        destination: str,
        start: datetime,
        limit: int = 5,
        regional_only: bool = True,
        track_now: bool = False,
        auto_widen: bool = False,
    ) -> SearchResult:
        res = SearchResult(regional_only=regional_only)
        res.origin = self.resolve(origin, "出发地")
        res.destination = self.resolve(destination, "目的地")
        if norm_name(res.origin.name) == norm_name(res.destination.name):
            res.notes.append("出发地和目的地是同一个车站")
            return res

        dest_keys = name_keys(res.destination.name, destination)
        min_dep = start.strftime("%y%m%d%H%M")
        first_hour = start.replace(minute=0, second=0, microsecond=0)

        stops: List[Stop] = []
        direct: List[Tuple[Stop, int]] = []
        shown: List[Tuple[Stop, int]] = []
        hidden = 0
        ok_calls = 0
        no_data = 0
        errors: List[str] = []
        with ThreadPoolExecutor(max_workers=6) as pool:
            for batch in (range(0, 3), range(3, MAX_ORIGIN_HOURS)):
                jobs = [
                    pool.submit(self._planned, eva, first_hour + timedelta(hours=k), (first_hour + timedelta(hours=k)).hour)
                    for k in batch
                    for eva in res.origin.evas
                ]
                for j in jobs:
                    try:
                        stops.extend(j.result())
                        ok_calls += 1
                    except _NoData:
                        no_data += 1
                    except Exception as e:  # noqa: BLE001
                        errors.append(f"{type(e).__name__}: {e}")
                direct = find_direct(stops, dest_keys, min_dep)
                shown = [(s, i) for s, i in direct if not regional_only or is_regional(s.train_name, s.category)]
                if len(shown) >= limit:
                    break
            if ok_calls == 0:
                if no_data and not errors:
                    raise OutOfWindow(start)
                raise DbUnavailable("德铁时刻表服务暂时无法访问：" + (errors[0] if errors else "无响应"))

            hidden = len(direct) - len(shown) if regional_only else 0
            if not shown and direct and regional_only and auto_widen:
                # 默认口径是月票区域车；该线路/时段只有长途车时自动放开，避免“明明有 ICE 却显示没有”
                shown, hidden, regional_only = list(direct), 0, False
                res.regional_only = False
                res.notes.append("该时段没有区域车（RE/RB/S），已为你显示 ICE/IC 等长途直达车")
            shown = shown[:limit]
            res.filtered_out = max(hidden, 0)
            db_log("trips", "direct", {"direct": len(direct), "shown": len(shown), "hidden": hidden})

            if not shown:
                if direct and regional_only:
                    res.notes.append("该时段只有 ICE/IC 等长途直达车，当前口径为仅区域车（RE/RB/S）")
                else:
                    res.notes.append("该时段没有直达车次；本查询只支持直达，换乘请到 DB Navigator 确认")
                return res

            # 到达时刻：到达站时刻表里同一趟车（id 前两段相同）的 ar.pt
            long_haul = any(not is_regional(s.train_name, s.category) for s, _ in shown)
            span = 5 if long_haul else 3
            dep_hours = sorted({(parse_dt(s.dp.get("pt")) or start).replace(minute=0) for s, _ in shown})
            h0, h1 = dep_hours[0], dep_hours[-1] + timedelta(hours=span)
            hours = []
            t = h0
            while t <= h1 and len(hours) < MAX_DEST_HOURS:
                hours.append(t)
                t += timedelta(hours=1)
            dest_jobs = [pool.submit(self._planned, eva, h, h.hour) for h in hours for eva in res.destination.evas]
            cur_o = [pool.submit(self._current, eva) for eva in res.origin.evas]
            cur_d = [pool.submit(self._current, eva) for eva in res.destination.evas]
            dest_stops: List[Stop] = []
            for j in dest_jobs:
                try:
                    dest_stops.extend(j.result())
                except Exception:  # noqa: BLE001  到达时刻缺失只影响展示
                    pass
            co: Dict[str, Stop] = {}
            for j in cur_o:
                co.update(j.result())
            cd: Dict[str, Stop] = {}
            for j in cur_d:
                cd.update(j.result())
            dest_idx = index_by_key(dest_stops)

        for st, idx in shown:
            res.trips.append(
                build_trip(st, idx, res.origin.name, res.destination.name, dest_idx.get(st.key), co.get(st.key), cd.get(st.key))
            )
        if hidden > 0:
            res.notes.append(f"另有 {hidden} 趟 ICE/IC 等长途直达车未显示（当前仅区域车 RE/RB/S）")
        if not any(t.get("arrival_time") for t in res.trips):
            res.notes.append("到达时刻暂缺（以 DB Navigator 为准）")
        return res


def parse_dt(v: Optional[str]) -> Optional[datetime]:
    from .trip_search import parse_ts

    return parse_ts(v or "")

