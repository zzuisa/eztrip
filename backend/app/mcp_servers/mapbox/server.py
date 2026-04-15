"""Mapbox MCP server (stdio) for Europe-friendly maps.

Tools exposed (stable names):
- geocode_forward
- geocode_reverse
- poi_search
- directions
- static_map

Auth:
- MAPBOX_ACCESS_TOKEN env var
"""

from __future__ import annotations

import os
from urllib.parse import quote
from typing import Any, Dict, List, Literal, Optional, Tuple

import httpx
from fastmcp import FastMCP


MAPBOX_GEOCODING_BASE = "https://api.mapbox.com/geocoding/v5/mapbox.places"
MAPBOX_SEARCHBOX_BASE = "https://api.mapbox.com/search/searchbox/v1/forward"
MAPBOX_DIRECTIONS_BASE = "https://api.mapbox.com/directions/v5/mapbox"
MAPBOX_STATIC_BASE = "https://api.mapbox.com/styles/v1/mapbox/streets-v12/static"

mcp = FastMCP("mapbox")


def _token() -> str:
    token = (os.getenv("MAPBOX_ACCESS_TOKEN") or os.getenv("MAPBOX_TOKEN") or "").strip()
    if not token:
        raise ValueError("MAPBOX_ACCESS_TOKEN is required")
    return token


def _client(timeout_s: float = 20.0) -> httpx.Client:
    return httpx.Client(timeout=timeout_s)


def _encode_q(q: str) -> str:
    return q.strip().replace("/", " ")


@mcp.tool
def geocode_forward(
    query: str,
    limit: int = 5,
    language: str = "en",
    country: str = "",
    types: str = "place,locality,neighborhood,poi,address",
) -> Dict[str, Any]:
    """Forward geocoding: query/address/place -> feature list with coordinates."""
    return _geocode_forward_impl(query, limit=limit, language=language, country=country, types=types)


def _geocode_forward_impl(
    query: str,
    limit: int = 5,
    language: str = "en",
    country: str = "",
    types: str = "place,locality,neighborhood,poi,address",
) -> Dict[str, Any]:
    """Internal forward geocoding implementation (callable in-process)."""
    q = _encode_q(query)
    url = f"{MAPBOX_GEOCODING_BASE}/{quote(q)}.json"
    params: Dict[str, Any] = {
        "access_token": _token(),
        "limit": max(1, min(int(limit), 10)),
        "language": language,
        "types": types or "place,locality,neighborhood,poi,address",
    }
    if country:
        params["country"] = country

    with _client() as c:
        r = c.get(url, params=params)
        r.raise_for_status()
        data = r.json()
    return data


def _searchbox_forward_impl(
    query: str,
    limit: int = 10,
    language: str = "en",
    country: str = "",
    types: str = "poi",
    proximity_longitude: Optional[float] = None,
    proximity_latitude: Optional[float] = None,
) -> Dict[str, Any]:
    """Searchbox forward search (preferred for POI candidates + mapbox_id)."""
    q = _encode_q(query)
    params: Dict[str, Any] = {
        "q": q,
        "limit": max(1, min(int(limit), 20)),
        "language": language,
        "access_token": _token(),
    }
    if country:
        params["country"] = country.lower()
    if proximity_longitude is not None and proximity_latitude is not None:
        params["proximity"] = f"{proximity_longitude},{proximity_latitude}"
    if types:
        # Searchbox expects category list for filtering; keep flexible by passing caller value.
        params["types"] = types
    with _client() as c:
        r = c.get(MAPBOX_SEARCHBOX_BASE, params=params)
        r.raise_for_status()
        return r.json()


@mcp.tool
def geocode_reverse(
    longitude: float,
    latitude: float,
    limit: int = 1,
    language: str = "en",
) -> Dict[str, Any]:
    """Reverse geocoding: coordinates -> place/address."""
    url = f"{MAPBOX_GEOCODING_BASE}/{longitude},{latitude}.json"
    params: Dict[str, Any] = {
        "access_token": _token(),
        "limit": max(1, min(int(limit), 5)),
        "language": language,
    }
    with _client() as c:
        r = c.get(url, params=params)
        r.raise_for_status()
        data = r.json()
    return data


@mcp.tool
def poi_search(
    keywords: str,
    city: str = "",
    limit: int = 8,
    language: str = "en",
    country: str = "",
    types: str = "place,locality,neighborhood,poi,address",
    proximity_longitude: Optional[float] = None,
    proximity_latitude: Optional[float] = None,
) -> Dict[str, Any]:
    """POI search via Searchbox: returns features with stable mapbox_id."""
    q = keywords.strip()
    if city:
        q = f"{q}, {city}"
    return _searchbox_forward_impl(
        q,
        limit=limit,
        language=language,
        country=country,
        types=types,
        proximity_longitude=proximity_longitude,
        proximity_latitude=proximity_latitude,
    )


DirectionsProfile = Literal["walking", "driving", "cycling"]


@mcp.tool
def directions(
    origin_longitude: float,
    origin_latitude: float,
    destination_longitude: float,
    destination_latitude: float,
    *,
    profile: DirectionsProfile = "walking",
    language: str = "en",
) -> Dict[str, Any]:
    """Directions between two coordinates (walking/driving/cycling)."""
    coords = f"{origin_longitude},{origin_latitude};{destination_longitude},{destination_latitude}"
    url = f"{MAPBOX_DIRECTIONS_BASE}/{profile}/{coords}"
    params: Dict[str, Any] = {
        "access_token": _token(),
        "geometries": "geojson",
        "overview": "full",
        "steps": "true",
        "language": language,
    }
    with _client() as c:
        r = c.get(url, params=params)
        r.raise_for_status()
        return r.json()


@mcp.tool
def static_map(
    center_longitude: float,
    center_latitude: float,
    *,
    zoom: float = 12,
    width: int = 600,
    height: int = 400,
    markers: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Generate a Mapbox Static Images URL. Markers format: [{lon,lat,label?,color?}]."""
    z = max(0.0, min(float(zoom), 22.0))
    w = max(200, min(int(width), 1280))
    h = max(200, min(int(height), 1280))

    overlays: List[str] = []
    for m in markers or []:
        lon = m.get("lon")
        lat = m.get("lat")
        if lon is None or lat is None:
            continue
        label = str(m.get("label") or "")
        color = str(m.get("color") or "ff0000").lstrip("#")
        # pin-s supports label a-z,0-9; if invalid, omit.
        pin = "pin-s"
        if label and len(label) == 1 and label.isalnum():
            pin = f"pin-s-{label}+{color}"
        else:
            pin = f"pin-s+{color}"
        overlays.append(f"{pin}({lon},{lat})")

    overlay_part = ",".join(overlays) if overlays else ""
    center = f"{center_longitude},{center_latitude},{z}"
    path = f"{overlay_part}/{center}/{w}x{h}" if overlay_part else f"{center}/{w}x{h}"
    url = f"{MAPBOX_STATIC_BASE}/{path}"
    url = f"{url}?access_token={_token()}"
    return {"url": url}


if __name__ == "__main__":
    mcp.run()

