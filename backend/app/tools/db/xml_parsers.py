"""DB XML/JSON 解析与归一化（确定性，不依赖 LLM）"""

import json
import re
import xml.etree.ElementTree as ET
from typing import Any, Dict, List

from ...models.schemas import DbStation, DbTrip


def extract_payload(result: Any) -> Any:
    """从 MCP 工具返回中提取 payload（兼容 XML 与 JSON 文本）"""
    if isinstance(result, (list, dict)):
        return result
    text = str(result)
    if text.lstrip().startswith("<"):
        return parse_xml(text)
    match = re.search(r"(\{.*\}|\[.*\])", text, flags=re.S)
    if not match:
        return []
    try:
        return json.loads(match.group(1))
    except Exception:
        return []


def parse_xml(text: str) -> Any:
    """解析德铁 MCP 返回 XML（stations / timetable）。"""
    try:
        root = ET.fromstring(text.strip())
    except Exception:
        return {"raw_xml": text}

    tag = root.tag.lower()
    if tag == "stations":
        stations: List[Dict[str, Any]] = []
        for st in root.findall(".//station"):
            if not isinstance(st.attrib, dict):
                continue
            stations.append(
                {
                    "id": st.attrib.get("eva") or st.attrib.get("id") or "",
                    "name": st.attrib.get("name") or "",
                    "type": "station",
                }
            )
        return stations

    if tag == "timetable":
        trips: List[Dict[str, Any]] = []
        for s in root.findall("./s"):
            tl = s.find("./tl")
            dp = s.find("./dp")
            ar = s.find("./ar")

            tl_attrib = tl.attrib if tl is not None and isinstance(tl.attrib, dict) else {}
            dp_attrib = dp.attrib if dp is not None and isinstance(dp.attrib, dict) else {}
            ar_attrib = ar.attrib if ar is not None and isinstance(ar.attrib, dict) else {}

            ppth = dp_attrib.get("ppth") or ar_attrib.get("ppth") or ""
            route = [p.strip() for p in str(ppth).split("|") if p.strip()] if ppth else []
            direction = route[-1] if route else ""

            category = tl_attrib.get("c") or ""
            number = tl_attrib.get("n") or ""
            line = dp_attrib.get("l") or tl_attrib.get("l") or ""

            # DB App：S/RE/RB 通常展示线路号；长途车保持 c+n（如 ICE 848）
            line_norm = str(line).strip()
            category_norm = str(category).strip()
            number_norm = str(number).strip()

            train_name = " ".join([x for x in [category_norm, number_norm] if x]).strip()
            if line_norm:
                upper = line_norm.upper()
                if upper.startswith("S") or upper.startswith("RE") or upper.startswith("RB"):
                    train_name = line_norm
            if not train_name:
                train_name = line_norm

            trips.append(
                {
                    "train_name": train_name,
                    "direction": direction,
                    "route": route,
                    "plannedWhen": dp_attrib.get("pt") or "",
                    "plannedPlatform": dp_attrib.get("pp") or "",
                }
            )
        return trips

    entries: List[Dict[str, Any]] = []
    for node in list(root):
        if not hasattr(node, "attrib"):
            continue
        item = {"_tag": node.tag}
        item.update({k: v for k, v in (node.attrib or {}).items()})
        for child in list(node):
            child_item = {"_tag": f"{node.tag}/{child.tag}"}
            child_item.update({k: v for k, v in (child.attrib or {}).items()})
            entries.append(child_item)
        entries.append(item)
    return {"xml_root": root.tag, "entries": entries}


def normalize_stations(payload: Any) -> List[DbStation]:
    if isinstance(payload, dict):
        payload = payload.get("data") or payload.get("stations") or payload.get("results") or []
    out: List[DbStation] = []
    if not isinstance(payload, list):
        return out
    for item in payload:
        if not isinstance(item, dict):
            continue
        out.append(
            DbStation(
                id=str(item.get("id", "")),
                name=item.get("name", ""),
                type=item.get("type", "station"),
                latitude=item.get("latitude"),
                longitude=item.get("longitude"),
                distance=item.get("distance"),
            )
        )
    return out


def normalize_trips(payload: Any, origin_name: str, destination_name: str) -> List[DbTrip]:
    if isinstance(payload, dict):
        payload = payload.get("data") or payload.get("trips") or payload.get("results") or []
    out: List[DbTrip] = []
    if not isinstance(payload, list):
        return out

    dest_lower = (destination_name or "").lower().strip()
    for item in payload:
        if not isinstance(item, dict):
            continue
        direction = item.get("direction") or item.get("destination") or item.get("to") or item.get("end") or ""
        route = " ".join(item.get("route", [])) if isinstance(item.get("route"), list) else ""
        if dest_lower:
            searchable = f"{direction} {route}".lower()
            if dest_lower not in searchable:
                continue

        train = item.get("train_name") or item.get("train") or item.get("line") or item.get("name") or ""
        dep_time = item.get("departure_time") or item.get("when") or item.get("plannedWhen") or item.get("departure") or ""
        arr_time = item.get("arrival_time") or item.get("arrival") or ""
        platform = item.get("platform") or item.get("plannedPlatform") or ""
        status = item.get("status") or ("cancelled" if item.get("cancelled") else "on_time")

        out.append(
            DbTrip(
                train_name=str(train),
                origin=origin_name,
                destination=str(destination_name),
                departure_time=str(dep_time),
                arrival_time=str(arr_time),
                platform=str(platform),
                status=str(status),
            )
        )
    return out


def is_month_ticket_train(t: DbTrip) -> bool:
    name = (t.train_name or "").strip().upper()
    return bool(name) and (name.startswith("RE") or name.startswith("RB") or name.startswith("S"))

