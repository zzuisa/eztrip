"""Mapbox MCP 服务封装"""

import os
import sys
import json
import traceback
from typing import Any, Dict, List, Optional, Tuple

from hello_agents.tools import MCPTool

from ..config import get_settings
from ..models.schemas import Location, POIInfo, RouteInfo


_mapbox_mcp_tool: Optional[MCPTool] = None


def get_mapbox_mcp_tool() -> MCPTool:
    global _mapbox_mcp_tool
    if _mapbox_mcp_tool is None:
        settings = get_settings()
        if not settings.mapbox_access_token:
            raise ValueError("Mapbox access token 未配置，请在 .env 设置 MAPBOX_ACCESS_TOKEN / mapbox_access_token")

        os.environ["MAPBOX_ACCESS_TOKEN"] = settings.mapbox_access_token
        _mapbox_mcp_tool = MCPTool(
            name="mapbox",
            description="Mapbox MCP 地图服务（欧洲可用）",
            server_command=[sys.executable, "-m", "app.mcp_servers.mapbox.server"],
            env={"MAPBOX_ACCESS_TOKEN": settings.mapbox_access_token},
            auto_expand=True,
        )
    return _mapbox_mcp_tool


class MapboxService:
    def __init__(self):
        self._settings = get_settings()
        self.mcp_tool = get_mapbox_mcp_tool()

    def _dbg(self, title: str, detail: str) -> None:
        if getattr(self._settings, "debug_mapbox", False):
            print(f"🧭 [MAPBOX 调试] {title}\n{detail}\n")

    def _call(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        try:
            if tool_name == "poi_search" and "country" not in arguments:
                arguments["country"] = ""

            self._dbg("准备调用工具", f"- tool: {tool_name}\n- arguments: {arguments}")
            result = self.mcp_tool.run({"action": "call_tool", "tool_name": tool_name, "arguments": arguments})

            if isinstance(result, str):
                # 若是错误文本，直接抛出，让上层日志可见
                if ("validation error" in result.lower()) or ("异步操作失败" in result):
                    self._dbg("工具返回错误文本", result[:1200])
                    raise RuntimeError(result)

                # hello_agents MCPTool 常把 JSON 包在字符串里：
                # "工具 'xxx' 执行结果:\n{...json...}"
                start = result.find("{")
                end = result.rfind("}")
                if start != -1 and end != -1 and end > start:
                    try:
                        parsed = json.loads(result[start:end + 1])
                        self._dbg("工具返回 JSON(已解析)", f"keys={list(parsed.keys()) if isinstance(parsed, dict) else type(parsed)}")
                        return parsed
                    except Exception:
                        self._dbg("工具返回文本(无法解析为 JSON)", result[:1200])
                        return result

                self._dbg("工具返回文本(非 JSON)", result[:1200])
                return result

            self._dbg("工具返回结构化数据", f"type={type(result)}")
            return result
        except Exception as e:
            self._dbg(
                "调用工具异常",
                f"- tool: {tool_name}\n- arguments: {arguments}\n- error: {type(e).__name__}: {e}\n- traceback:\n{traceback.format_exc()}",
            )
            raise

    def _first_feature_center(self, geocode_json: Dict[str, Any]) -> Optional[Tuple[float, float]]:
        features = geocode_json.get("features") if isinstance(geocode_json, dict) else None
        if not isinstance(features, list) or not features:
            return None
        center = features[0].get("center")
        if isinstance(center, list) and len(center) >= 2:
            return float(center[0]), float(center[1])
        return None

    def _pick_best_feature(self, geocode_json: Dict[str, Any], preferred_name: Optional[str] = None) -> Optional[Dict[str, Any]]:
        features = geocode_json.get("features") if isinstance(geocode_json, dict) else None
        if not isinstance(features, list) or not features:
            return None
        if not preferred_name:
            return features[0]
        pn = preferred_name.strip().lower()
        # 1) exact match on text
        for f in features:
            t = str(f.get("text") or "").strip().lower()
            if t and t == pn:
                return f
        # 2) place_name contains preferred name and is poi
        for f in features:
            place_name = str(f.get("place_name") or "").lower()
            place_type = f.get("place_type") or []
            if pn and pn in place_name and isinstance(place_type, list) and ("poi" in place_type):
                return f
        # 3) any poi
        for f in features:
            place_type = f.get("place_type") or []
            if isinstance(place_type, list) and ("poi" in place_type):
                return f
        return features[0]

    def _extract_feature_center(self, f: Dict[str, Any]) -> Optional[Tuple[float, float]]:
        center = f.get("center")
        if isinstance(center, list) and len(center) >= 2:
            return float(center[0]), float(center[1])
        geom = f.get("geometry") or {}
        coords = geom.get("coordinates")
        if isinstance(coords, list) and len(coords) >= 2:
            return float(coords[0]), float(coords[1])
        props = f.get("properties") or {}
        pcoords = props.get("coordinates") or {}
        lon = pcoords.get("longitude")
        lat = pcoords.get("latitude")
        if lon is not None and lat is not None:
            return float(lon), float(lat)
        return None

    def _extract_feature_name(self, f: Dict[str, Any]) -> str:
        props = f.get("properties") or {}
        return str(f.get("text") or props.get("name") or "").strip()

    def _extract_feature_address(self, f: Dict[str, Any]) -> str:
        props = f.get("properties") or {}
        return str(f.get("place_name") or props.get("full_address") or props.get("address") or "").strip()

    def _extract_feature_mapbox_id(self, f: Dict[str, Any]) -> str:
        props = f.get("properties") or {}
        return str(props.get("mapbox_id") or f.get("id") or "").strip()

    def search_poi(
        self,
        keywords: str,
        city: str,
        citylimit: bool = True,
        *,
        country: str = "",
        proximity: Optional[Tuple[float, float]] = None,
        limit: int = 10,
        language: str = "en",
        types: str = "poi",
        strict_poi_only: bool = True,
        enforce_country_filter: bool = False,
    ) -> List[POIInfo]:
        # citylimit 在 Mapbox 里无法完全等价，这里用 city 拼接作为约束
        country_code = country or self._infer_country_code(city)
        safe_limit = max(1, min(int(limit), 20))
        args: Dict[str, Any] = {
            "keywords": keywords,
            "city": city,
            "country": country_code,
            "limit": safe_limit,
            "language": language or "en",
            "types": types or "poi",
        }
        if proximity:
            args["proximity_longitude"] = proximity[0]
            args["proximity_latitude"] = proximity[1]
        raw = self._call(
            "poi_search",
            args,
        )
        if not isinstance(raw, dict):
            return []
        features = raw.get("features", [])
        out: List[POIInfo] = []
        for f in features if isinstance(features, list) else []:
            center = self._extract_feature_center(f)
            if not center:
                continue
            place_type = f.get("place_type") or []
            props = f.get("properties") or {}
            feature_type = str(props.get("feature_type") or "").lower()
            is_poi = (isinstance(place_type, list) and "poi" in place_type) or feature_type == "poi"
            if strict_poi_only and not is_poi:
                continue
            poi = POIInfo(
                id=str(f.get("id", "")),
                name=self._extract_feature_name(f),
                type="poi",
                address=self._extract_feature_address(f),
                location=Location(longitude=float(center[0]), latitude=float(center[1])),
                tel=None,
                mapbox_id=self._extract_feature_mapbox_id(f),
            )
            out.append(poi)
        if enforce_country_filter:
            out = self._filter_by_country_boundary(out, country_code)
        return out

    def resolve_city_in_country(
        self,
        city: str,
        *,
        country_code: str = "",
        limit: int = 3,
        language: str = "en",
    ) -> Optional[Dict[str, Any]]:
        """校验并归一化城市，返回城市名、国家码和中心点。"""
        city_text = (city or "").strip()
        if not city_text:
            return None

        cc = (country_code or self._infer_country_code(city_text)).strip().upper()
        raw = self._call(
            "geocode_forward",
            {
                "query": city_text,
                "limit": max(1, min(int(limit), 10)),
                "language": language or "en",
                "country": cc,
                "types": "place,locality",
            },
        )
        if not isinstance(raw, dict):
            return None
        best = self._pick_best_feature(raw, preferred_name=city_text)
        if not isinstance(best, dict):
            return None
        center = self._extract_feature_center(best)
        if not center:
            return None

        props = best.get("properties") or {}
        context = best.get("context") if isinstance(best.get("context"), list) else []
        feature_country = str(props.get("country") or "").strip().upper()
        if not feature_country:
            for ctx in context:
                if not isinstance(ctx, dict):
                    continue
                cid = str(ctx.get("id") or "")
                short = str(ctx.get("short_code") or "")
                if cid.startswith("country.") and short:
                    feature_country = short.strip().upper()
                    break
        if not feature_country:
            feature_country = cc
        if cc and feature_country and feature_country != cc:
            return None

        normalized_city = str(best.get("text") or city_text).strip() or city_text
        return {
            "city": normalized_city,
            "country_code": (feature_country or cc).upper(),
            "location": Location(longitude=float(center[0]), latitude=float(center[1])),
        }

    def _infer_country_code(self, city_or_country: str) -> str:
        s = (city_or_country or "").strip().lower()
        if not s:
            return ""
        mapping = {
            "france": "FR",
            "法国": "FR",
            "paris": "FR",
            "巴黎": "FR",
            "germany": "DE",
            "德国": "DE",
            "berlin": "DE",
            "柏林": "DE",
        }
        return mapping.get(s, "")

    def _filter_by_country_boundary(self, pois: List[POIInfo], country_code: str) -> List[POIInfo]:
        if not pois or not country_code:
            return pois
        # 先地址文本过滤，再经纬度 bbox 过滤，双保险
        if country_code == "FR":
            # Metropolitan France bbox roughly: lon [-5.5, 9.8], lat [41.0, 51.5]
            min_lon, max_lon, min_lat, max_lat = -5.5, 9.8, 41.0, 51.5
            keep: List[POIInfo] = []
            for p in pois:
                addr = (p.address or "").lower()
                lon = p.location.longitude
                lat = p.location.latitude
                if "france" not in addr:
                    continue
                if not (min_lon <= lon <= max_lon and min_lat <= lat <= max_lat):
                    continue
                keep.append(p)
            return keep
        return pois

    def geocode(
        self,
        address: str,
        city: Optional[str] = None,
        *,
        preferred_name: Optional[str] = None,
        country: str = "",
        types: str = "poi,address,place,locality,neighborhood",
        limit: int = 5,
        language: str = "en",
    ) -> Optional[Location]:
        q = address
        if city:
            # 避免把 “..., France” 这种地址再次拼上 “法国”
            a = (address or "").lower()
            c = (city or "").lower()
            if c and c not in a:
                q = f"{address}, {city}"
        raw = self._call(
            "geocode_forward",
            {"query": q, "limit": limit, "language": "en", "country": country, "types": types},
        )
        if not isinstance(raw, dict):
            return None
        best = self._pick_best_feature(raw, preferred_name=preferred_name)
        if not best:
            return None
        center = best.get("center")
        if not (isinstance(center, list) and len(center) >= 2):
            return None
        lon, lat = float(center[0]), float(center[1])
        return Location(longitude=lon, latitude=lat)

    def plan_route(
        self,
        origin_address: str,
        destination_address: str,
        origin_city: Optional[str] = None,
        destination_city: Optional[str] = None,
        route_type: str = "walking",
    ) -> Dict[str, Any]:
        origin_loc = self.geocode(origin_address, origin_city)
        dest_loc = self.geocode(destination_address, destination_city)
        if not origin_loc or not dest_loc:
            return {"error": "无法地理编码起点/终点"}

        profile_map = {"walking": "walking", "driving": "driving", "cycling": "cycling", "transit": "walking"}
        profile = profile_map.get(route_type, "walking")
        raw = self._call(
            "directions",
            {
                "origin_longitude": origin_loc.longitude,
                "origin_latitude": origin_loc.latitude,
                "destination_longitude": dest_loc.longitude,
                "destination_latitude": dest_loc.latitude,
                "profile": profile,
                "language": "en",
            },
        )
        if not isinstance(raw, dict):
            return {"error": "路线规划失败"}
        routes = raw.get("routes") if isinstance(raw, dict) else None
        if not isinstance(routes, list) or not routes:
            return {"error": "无可用路线"}
        r0 = routes[0]
        distance = float(r0.get("distance") or 0.0)
        duration = int(r0.get("duration") or 0)
        summary = str(r0.get("summary") or "")

        static = self._call(
            "static_map",
            {
                "center_longitude": origin_loc.longitude,
                "center_latitude": origin_loc.latitude,
                "zoom": 11,
                "width": 800,
                "height": 480,
                "markers": [
                    {"lon": origin_loc.longitude, "lat": origin_loc.latitude, "label": "A", "color": "00aaff"},
                    {"lon": dest_loc.longitude, "lat": dest_loc.latitude, "label": "B", "color": "ff0000"},
                ],
            },
        )

        return {
            "route": RouteInfo(
                distance=distance,
                duration=duration,
                route_type=route_type,
                description=summary or f"{route_type} route",
            ).model_dump(),
            "static_map": static,
            "origin": origin_loc.model_dump(),
            "destination": dest_loc.model_dump(),
            "raw": raw,
        }


_mapbox_service: Optional[MapboxService] = None


def get_mapbox_service() -> MapboxService:
    global _mapbox_service
    if _mapbox_service is None:
        _mapbox_service = MapboxService()
    return _mapbox_service

