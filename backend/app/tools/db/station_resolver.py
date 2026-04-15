"""站点解析/选择（中文别名、Hbf 默认、候选合并去重）"""

import re
from typing import Dict, List, Optional

from ...models.schemas import DbStation
from .xml_parsers import extract_payload, normalize_stations


class DbStationResolver:
    def __init__(self, call_tool):
        # call_tool(tool_name:str, arguments:dict) -> Any
        self._call_tool = call_tool

    def _contains_cjk(self, s: str) -> bool:
        return bool(re.search(r"[\u4e00-\u9fff]", s or ""))

    def _fix_mojibake(self, s: str) -> str:
        markers = ["Ã", "æ", "ç", "å"]
        if not s or not any(m in s for m in markers):
            return s
        try:
            return s.encode("latin1").decode("utf-8")
        except Exception:
            return s

    def _umlaut_variants(self, s: str) -> List[str]:
        out = [s]
        repl = [("ae", "ä"), ("oe", "ö"), ("ue", "ü"), ("Ae", "Ä"), ("Oe", "Ö"), ("Ue", "Ü")]
        v = s
        for a, b in repl:
            v = v.replace(a, b)
        if v != s:
            out.append(v)
        return out

    def _zh_aliases(self, s: str) -> List[str]:
        raw = (s or "").strip()
        if not raw:
            return []

        core = re.sub(r"(火车站|车站|火车|站|总站)$", "", raw).strip()
        core = re.sub(r"\s+(Hbf|Hauptbahnhof)$", "", core, flags=re.I).strip()
        core = re.sub(r"\s+", " ", core)

        alias_map: Dict[str, List[str]] = {
            "杜塞尔多夫": ["Düsseldorf"],
            "杜塞": ["Düsseldorf"],
            "杜赛": ["Düsseldorf"],
            "杜伊斯堡": ["Duisburg"],
            "杜伊": ["Duisburg"],
            "杜堡": ["Duisburg"],
            "法兰克福": ["Frankfurt"],
            "柏林": ["Berlin"],
            "慕尼黑": ["München", "Munich"],
            "科隆": ["Köln", "Cologne"],
            "汉堡": ["Hamburg"],
            "斯图加特": ["Stuttgart"],
            "汉诺威": ["Hannover"],
            "多特蒙德": ["Dortmund"],
            "埃森": ["Essen"],
        }

        out: List[str] = []
        raw2 = re.sub(r"\s+(Hbf|Hauptbahnhof)$", "", raw, flags=re.I).strip()
        for key in [raw, raw2, core]:
            if key in alias_map:
                out.extend(alias_map[key])
        return list(dict.fromkeys([x for x in out if x]))

    def search_candidates(self, station_tool: str, query: str) -> List[DbStation]:
        base = self._fix_mojibake(query or "")
        patterns: List[str] = []

        if self._contains_cjk(base):
            for mapped in self._zh_aliases(base):
                for v in self._umlaut_variants(mapped):
                    if v and v not in patterns:
                        patterns.append(v)
        for v in self._umlaut_variants(base):
            if v and v not in patterns:
                patterns.append(v)

        q_lower = base.lower()
        if "hbf" not in q_lower and "hauptbahnhof" not in q_lower:
            extra: List[str] = []
            for p in list(patterns):
                extra.extend([f"{p} Hbf", f"{p} Hauptbahnhof"])
            for p in extra:
                if p not in patterns:
                    patterns.append(p)

        merged: List[DbStation] = []
        seen: set[str] = set()
        for p in patterns:
            raw = self._call_tool(station_tool, {"pattern": p})
            items = normalize_stations(extract_payload(raw))
            for s in items:
                if not s.id or s.id in seen:
                    continue
                merged.append(s)
                seen.add(s.id)
        return merged

    def pick_best(self, stations: List[DbStation], query: str) -> Optional[DbStation]:
        if not stations:
            return None
        q = (query or "").lower().strip()
        wants_hbf = ("hbf" in q) or ("hauptbahnhof" in q)

        for s in stations:
            name = (s.name or "").lower().strip()
            if name == q and s.id:
                return s

        contains: List[DbStation] = []
        for s in stations:
            name = (s.name or "").lower().strip()
            if q and q in name and s.id:
                contains.append(s)
        if contains:
            if not wants_hbf:
                for s in contains:
                    name = (s.name or "").lower()
                    if (" hbf" in name) or ("hauptbahnhof" in name):
                        return s
            return contains[0]

        for s in stations:
            name = (s.name or "").lower()
            if (" hbf" in name) or ("hauptbahnhof" in name):
                return s
        return stations[0]

