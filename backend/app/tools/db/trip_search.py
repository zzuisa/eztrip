"""德铁直达车次搜索核心：XML 解析、站名归一化、目的地匹配、到达时刻/实时状态合并。

只做确定性数据处理（无网络、无 LLM），便于离线测试。
DB Timetables 的 getPlannedTimetable 只给“某站某小时的出发/到达”，每条 <s> 的 dp/ppth 是该车出发后
依次停靠的站（站名格式如 "Frankfurt(Main)Hbf"、"Münster(Westf)Hbf"），因此必须先归一化再匹配。
"""

from __future__ import annotations

import json
import re
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

_STOP_WORDS = {"am", "main", "an", "der", "bei"}


def norm_name(s: str) -> str:
    """站名归一化： 去重音/括号注释/标点，Hauptbahnhof->hbf。"Frankfurt(Main)Hbf" == "Frankfurt Hbf (tief)"."""
    s = (s or "").strip().lower().replace("ß", "ss")
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"\([^)]*\)", " ", s)
    s = s.replace("hauptbahnhof", "hbf")
    s = re.sub(r"[^a-z0-9]+", " ", s).strip()
    return s


def loose_name(s: str) -> str:
    """更宽松的键：额外去掉 am/main 等连接词（Frankfurt am Main Hbf == Frankfurt Hbf）。"""
    return " ".join(t for t in norm_name(s).split() if t not in _STOP_WORDS)


def name_keys(*names: str) -> Set[str]:
    out: Set[str] = set()
    for n in names:
        if not n:
            continue
        out.add(norm_name(n))
        out.add(loose_name(n))
    out.discard("")
    return out


# ---------- XML ----------

def extract_xml(raw: Any) -> str:
    """MCP 返回可能是 XML 文本，或超长时被包装成 {"truncated":true,"preview":...} 的 JSON。"""
    text = raw if isinstance(raw, str) else str(raw)
    t = text.lstrip()
    if t.startswith("{") and '"preview"' in t[:400]:
        try:
            obj = json.loads(t)
            text = str(obj.get("preview") or "")
            # 截断的 XML：补齐到最后一个完整 <s>…</s>
            cut = text.rfind("</s>")
            if cut >= 0:
                text = text[: cut + 4] + "</timetable>"
        except Exception:
            return ""
    return text.strip()


def parse_ts(v: str) -> Optional[datetime]:
    """YYMMDDHHmm -> datetime（柏林本地时间，无时区）。"""
    m = re.fullmatch(r"(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})", (v or "").strip())
    if not m:
        return None
    yy, mo, dd, hh, mi = (int(x) for x in m.groups())
    try:
        return datetime(2000 + yy, mo, dd, hh, mi)
    except ValueError:
        return None


def minutes_between(a: str, b: str) -> Optional[int]:
    da, db = parse_ts(a), parse_ts(b)
    if not da or not db:
        return None
    return int((db - da).total_seconds() // 60)


def trip_key(sid: str) -> str:
    """<s id="-123-2610281926-15">：末段是该站的停靠序号，同一趟车在不同站不同；前两段标识这一趟车。"""
    return (sid or "").rsplit("-", 1)[0]


@dataclass
class Stop:
    sid: str
    key: str
    train_name: str
    category: str
    dp: Dict[str, str] = field(default_factory=dict)
    ar: Dict[str, str] = field(default_factory=dict)
    dp_path: List[str] = field(default_factory=list)
    ar_path: List[str] = field(default_factory=list)


def _train_name(tl: Dict[str, str], dp: Dict[str, str], ar: Dict[str, str]) -> str:
    cat, num = (tl.get("c") or "").strip(), (tl.get("n") or "").strip()
    line = (dp.get("l") or ar.get("l") or tl.get("l") or "").strip()
    name = " ".join(x for x in (cat, num) if x)
    if line and line.upper().startswith(("S", "RE", "RB")):
        name = line
    return name or line or (dp.get("fb") or ar.get("fb") or "")


def parse_stops(raw: Any) -> List[Stop]:
    xml = extract_xml(raw)
    if not xml.startswith("<"):
        return []
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return []
    out: List[Stop] = []
    for s in root.findall("./s"):
        tl = s.find("./tl")
        dp = s.find("./dp")
        ar = s.find("./ar")
        tla = dict(tl.attrib) if tl is not None else {}
        dpa = dict(dp.attrib) if dp is not None else {}
        ara = dict(ar.attrib) if ar is not None else {}
        sid = s.attrib.get("id", "")
        out.append(
            Stop(
                sid=sid,
                key=trip_key(sid),
                train_name=_train_name(tla, dpa, ara),
                category=(tla.get("c") or "").strip(),
                dp=dpa,
                ar=ara,
                dp_path=[p.strip() for p in (dpa.get("ppth") or "").split("|") if p.strip()],
                ar_path=[p.strip() for p in (ara.get("ppth") or "").split("|") if p.strip()],
            )
        )
    return out


# ---------- 筛选 ----------

REGIONAL_PREFIX = ("RE", "RB", "S")


def is_regional(train_name: str, category: str = "") -> bool:
    n = (train_name or "").strip().upper()
    c = (category or "").strip().upper()
    return n.startswith(REGIONAL_PREFIX) or c in {"RE", "RB", "S", "IRE", "RS", "FEX"}


def find_direct(stops: Iterable[Stop], dest_keys: Set[str], min_dep: Optional[str]) -> List[Tuple[Stop, int]]:
    """出发站时刻表里“出发后经停目的地”的车次（直达）。返回 (stop, 目的地在 dp_path 中的下标)。"""
    seen: Set[str] = set()
    out: List[Tuple[Stop, int]] = []
    for st in stops:
        pt = st.dp.get("pt") or ""
        if not pt or st.key in seen:
            continue
        if min_dep and pt < min_dep:
            continue
        idx = next(
            (i for i, p in enumerate(st.dp_path) if norm_name(p) in dest_keys or loose_name(p) in dest_keys),
            -1,
        )
        if idx < 0:
            continue
        seen.add(st.key)
        out.append((st, idx))
    out.sort(key=lambda x: x[0].dp.get("pt") or "")
    return out


def index_by_key(stops: Iterable[Stop]) -> Dict[str, Stop]:
    out: Dict[str, Stop] = {}
    for st in stops:
        out.setdefault(st.key, st)
    return out


def _delay(planned: str, changed: str) -> Optional[int]:
    if not planned or not changed:
        return None
    return minutes_between(planned, changed)


def build_trip(
    st: Stop,
    stops_between: int,
    origin_name: str,
    dest_name: str,
    dest_stop: Optional[Stop],
    cur_origin: Optional[Stop],
    cur_dest: Optional[Stop],
) -> Dict[str, Any]:
    dep_pt = st.dp.get("pt") or ""
    arr_pt = (dest_stop.ar.get("pt") if dest_stop else "") or ""
    # 实时：dp/ar 上的 ct(changed time) cp(changed platform) cs(c=取消)
    cdp = (cur_origin.dp if cur_origin else {}) or {}
    car_ = (cur_dest.ar if cur_dest else {}) or {}
    cancelled = cdp.get("cs") == "c" or car_.get("cs") == "c"
    dep_delay = _delay(dep_pt, cdp.get("ct") or "")
    arr_delay = _delay(arr_pt, car_.get("ct") or "")
    platform = cdp.get("cp") or st.dp.get("pp") or ""
    status = "cancelled" if cancelled else ("delayed" if (dep_delay or 0) >= 3 or (arr_delay or 0) >= 5 else "on_time")
    last = st.dp_path[-1] if st.dp_path else ""
    return {
        "train_name": st.train_name,
        "origin": origin_name,
        "destination": dest_name,
        "departure_time": dep_pt,
        "arrival_time": arr_pt,
        "actual_departure_time": cdp.get("ct") or "",
        "actual_arrival_time": car_.get("ct") or "",
        "platform": platform,
        "platform_changed": bool(cdp.get("cp") and cdp.get("cp") != st.dp.get("pp")),
        "status": status,
        "delay_min": dep_delay if dep_delay and dep_delay > 0 else 0,
        "arrival_delay_min": arr_delay if arr_delay and arr_delay > 0 else 0,
        "duration_min": minutes_between(dep_pt, arr_pt) if arr_pt else None,
        "direction": last,
        "stops_between": stops_between,
        "category": st.category,
    }

