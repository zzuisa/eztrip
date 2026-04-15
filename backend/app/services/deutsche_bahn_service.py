"""Deutsche Bahn查询服务"""

from typing import Any, Dict, List

import httpx

from ..config import get_settings
from ..models.schemas import DbStation, DbTrip
from ..tools.db.debug import db_log, DbTimer
from ..tools.db.mcp_gateway import DbMcpGateway
from ..tools.db.station_resolver import DbStationResolver
from ..tools.db.xml_parsers import extract_payload, normalize_stations, normalize_trips, is_month_ticket_train


class DeutscheBahnService:
    """德铁查询服务封装"""

    def __init__(self):
        self.settings = get_settings()
        self.base_url = self.settings.db_api_base_url.rstrip("/")
        self.timeout = self.settings.db_timeout_seconds

    def _build_headers(self) -> Dict[str, str]:
        headers: Dict[str, str] = {"Accept": "application/json"}
        if self.settings.db_api_key:
            headers["Authorization"] = f"Bearer {self.settings.db_api_key}"
        return headers

    def _extract_coords(self, item: Dict[str, Any]) -> Dict[str, Any]:
        location = item.get("location") or {}
        lat = location.get("latitude")
        lon = location.get("longitude")
        if lat is None and isinstance(item.get("latitude"), (int, float)):
            lat = item.get("latitude")
        if lon is None and isinstance(item.get("longitude"), (int, float)):
            lon = item.get("longitude")
        return {"latitude": lat, "longitude": lon}

    def _normalize_stations(self, data: Any) -> List[DbStation]:
        stations: List[DbStation] = []
        if not isinstance(data, list):
            return stations
        for item in data:
            if not isinstance(item, dict):
                continue
            coords = self._extract_coords(item)
            stations.append(
                DbStation(
                    id=str(item.get("id", "")),
                    name=item.get("name", ""),
                    type=item.get("type", ""),
                    latitude=coords["latitude"],
                    longitude=coords["longitude"],
                    distance=item.get("distance"),
                )
            )
        return stations

    def search_stations(self, query: str, limit: int = 10, language: str = "de") -> List[DbStation]:
        """查询站点"""
        params = {
            "query": query,
            "results": limit,
            "language": language,
            "stops": "true",
            "addresses": "false",
            "poi": "false",
        }
        url = f"{self.base_url}/locations"
        with httpx.Client(timeout=self.timeout, headers=self._build_headers()) as client:
            resp = client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()

        return self._normalize_stations(data)

    def query_trips(
        self,
        origin: str,
        destination: str,
        date: str,
        hour: str,
        language: str = "de",
        min_departure_time: str | None = None,
        timetable_tool_override: str | None = None,
        limit: int = 5,
        month_ticket_only: bool = True,
    ) -> List[DbTrip]:
        """
        HTTP模式下的兜底实现（仅在 MCP 不可用时使用）：
        目前 DB 功能主路径是 MCP + timetables，本兜底只保留最小可用逻辑。
        """
        return []


class DeutscheBahnMcpService(DeutscheBahnService):
    """通过SSE MCP服务查询德铁数据"""

    def __init__(self):
        super().__init__()
        self._gateway = DbMcpGateway()
        self._tool_names = self._gateway.list_tool_names()
        self._resolver = DbStationResolver(self._gateway.call_tool)

    def _call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        return self._gateway.call_tool(tool_name, arguments)

    def _resolve_tool_name(self, candidates: List[str], keyword_hints: List[str]) -> str:
        # 1) 优先精确命中常见别名
        lower_map = {name.lower(): name for name in self._tool_names}
        for candidate in candidates:
            if candidate.lower() in lower_map:
                return lower_map[candidate.lower()]

        # 2) 其次关键词模糊匹配
        for name in self._tool_names:
            lower_name = name.lower()
            if all(hint in lower_name for hint in keyword_hints):
                return name

        # 3) 最后兜底：返回候选首项（便于暴露明确错误）
        return candidates[0]

    def search_stations(self, query: str, limit: int = 10, language: str = "de") -> List[DbStation]:
        try:
            tool_name = self._resolve_tool_name(
                candidates=[
                    "findStations",
                    "search_stations",
                    "station_search",
                    "get_stations",
                    "locations",
                    "db_stations",
                ],
                keyword_hints=["station"],
            )
            args = {"pattern": query}
            raw = self._call_tool(tool_name, args)
            payload = extract_payload(raw)
            stations = normalize_stations(payload)
            return stations[:limit]
        except Exception:
            # MCP不可用时回退到HTTP方案，避免接口长时间卡死
            return super().search_stations(query=query, limit=limit, language=language)

    def query_trips(
        self,
        origin: str,
        destination: str,
        date: str,
        hour: str,
        language: str = "de",
        min_departure_time: str | None = None,
        timetable_tool_override: str | None = None,
        limit: int = 5,
        month_ticket_only: bool = True,
    ) -> List[DbTrip]:
        try:
            request_id = f"trips-{origin}-{destination}-{date}-{hour}"
            timer = DbTimer(request_id)

            station_tool = self._resolve_tool_name(
                candidates=["findStations", "search_stations", "station_search", "get_stations"],
                keyword_hints=["station"],
            )
            timetable_tool = timetable_tool_override or self._resolve_tool_name(
                candidates=["getPlannedTimetable", "planned_timetable", "timetable_planned", "getCurrentTimetable"],
                keyword_hints=["planned", "timetable"],
            )

            timer.mark("开始：查询站点(findStations)")
            origin_stations = self._resolver.search_candidates(station_tool, origin)
            dest_stations = self._resolver.search_candidates(station_tool, destination)
            db_log(request_id, "origin_stations", [s.model_dump() for s in origin_stations[:5]])
            db_log(request_id, "dest_stations", [s.model_dump() for s in dest_stations[:5]])
            timer.mark("站点解析完成")
            if not origin_stations or not dest_stations:
                return []

            origin_station = self._resolver.pick_best(origin_stations, origin) or origin_stations[0]
            destination_station = self._resolver.pick_best(dest_stations, destination) or dest_stations[0]
            db_log(
                request_id,
                "chosen_stations",
                {"origin": origin_station.model_dump(), "destination": destination_station.model_dump()},
            )

            timer.mark("开始：查询时刻表(getPlannedTimetable)")
            timetable_raw = self._call_tool(
                timetable_tool,
                {"evaNo": origin_station.id, "date": date, "hour": hour},
            )
            db_log(request_id, "timetable_raw", timetable_raw)
            payload = extract_payload(timetable_raw)
            trips = normalize_trips(
                payload=payload,
                origin_name=origin_station.name,
                destination_name=destination_station.name,
            )
            # 按“月票列车（RE/RB/S）”过滤，并只取最近5趟
            if month_ticket_only:
                trips = [t for t in trips if is_month_ticket_train(t)]
            # time=now 时：过滤“当前时刻之后”的车（departure_time 通常是 YYMMDDHHmm）
            if min_departure_time:
                md = str(min_departure_time).strip()
                trips = [t for t in trips if (t.departure_time or "").strip() >= md]
            trips = trips[: max(1, min(int(limit or 5), 50))]
            db_log(request_id, "trips_filtered", [t.model_dump() for t in trips[:20]])
            timer.mark("车次过滤完成")
            return trips
        except Exception:
            return super().query_trips(
                origin=origin,
                destination=destination,
                date=date,
                hour=hour,
                language=language,
                limit=limit,
                month_ticket_only=month_ticket_only,
            )


_db_service = None


def get_deutsche_bahn_service() -> DeutscheBahnService:
    """获取德铁服务实例(单例模式)"""
    global _db_service
    if _db_service is None:
        settings = get_settings()
        _db_service = DeutscheBahnMcpService() if settings.enable_db_mcp else DeutscheBahnService()
    return _db_service

