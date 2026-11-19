"""Deutsche Bahn 查询服务（MCP Timetables 为主路径）"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx

from ..config import get_settings
from ..models.schemas import DbStation
from ..tools.db.debug import db_log
from ..tools.db.mcp_gateway import DbMcpGateway
from ..tools.db.searcher import DbTripSearcher, DbUnavailable, SearchResult
from ..tools.db.station_resolver import DbStationResolver
from ..tools.db.xml_parsers import extract_payload, normalize_stations


class DeutscheBahnService:
    """HTTP 兜底（v6.db.transport.rest）：仅提供站点查询；车次查询必须走 MCP。"""

    def __init__(self):
        self.settings = get_settings()
        self.base_url = self.settings.db_api_base_url.rstrip("/")
        self.timeout = self.settings.db_timeout_seconds

    def _build_headers(self) -> Dict[str, str]:
        headers: Dict[str, str] = {"Accept": "application/json"}
        if self.settings.db_api_key:
            headers["Authorization"] = f"Bearer {self.settings.db_api_key}"
        return headers

    def search_stations(self, query: str, limit: int = 10, language: str = "de") -> List[DbStation]:
        params = {"query": query, "results": limit, "language": language, "stops": "true", "addresses": "false", "poi": "false"}
        with httpx.Client(timeout=self.timeout, headers=self._build_headers()) as client:
            resp = client.get(f"{self.base_url}/locations", params=params)
            resp.raise_for_status()
            data = resp.json()
        out: List[DbStation] = []
        for item in data if isinstance(data, list) else []:
            if isinstance(item, dict):
                loc = item.get("location") or {}
                out.append(
                    DbStation(
                        id=str(item.get("id", "")),
                        name=item.get("name", ""),
                        type=item.get("type", ""),
                        latitude=loc.get("latitude"),
                        longitude=loc.get("longitude"),
                        distance=item.get("distance"),
                    )
                )
        return out

    def search_trips(self, **_: Any) -> SearchResult:
        raise DbUnavailable("德铁 MCP 未启用（ENABLE_DB_MCP=false）")


class DeutscheBahnMcpService(DeutscheBahnService):
    """通过 SSE MCP（db-timetable-mcp）查询德铁时刻表。"""

    def __init__(self):
        super().__init__()
        # 不在构造时探测 MCP：MCP 容器晚启动/重启时，旧实现会把空工具列表永久缓存下来
        self._gateway = DbMcpGateway()
        self._resolver = DbStationResolver(self._gateway.call_tool)
        self._searcher = DbTripSearcher(self._gateway.call_tool, self._resolver)

    def search_stations(self, query: str, limit: int = 10, language: str = "de") -> List[DbStation]:
        try:
            raw = self._gateway.call_tool("findStations", {"pattern": query})
            return normalize_stations(extract_payload(raw))[:limit]
        except Exception as e:  # noqa: BLE001
            raise DbUnavailable(f"站点查询失败：{type(e).__name__}") from e

    def search_trips(
        self,
        *,
        origin: str,
        destination: str,
        start: datetime,
        limit: int = 5,
        regional_only: bool = True,
        auto_widen: bool = False,
    ) -> SearchResult:
        db_log("trips", "search", {"o": origin, "d": destination, "start": str(start), "limit": limit, "regional": regional_only})
        return self._searcher.search(origin, destination, start, limit=limit, regional_only=regional_only, auto_widen=auto_widen)


_db_service: Optional[DeutscheBahnService] = None


def get_deutsche_bahn_service() -> DeutscheBahnService:
    global _db_service
    if _db_service is None:
        settings = get_settings()
        _db_service = DeutscheBahnMcpService() if settings.enable_db_mcp else DeutscheBahnService()
    return _db_service

