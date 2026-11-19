"""旅途节奏：默认轻松自在，除非用户明确要求紧凑 / 深度。

- detect_pace：从偏好文本判断 relaxed / standard / tight。
- min_stay：各类地点在“轻松”节奏下的最短停留（温泉 / 水疗 ≥ 3.5 小时）。
- pace_block：写进编排提示词的节奏规则。
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

RELAXED, STANDARD, TIGHT = "relaxed", "standard", "tight"

_TIGHT = re.compile(r"特种兵|紧凑|赶行程|多打卡|打卡多|高效|暴走|压缩|一天.{0,3}(?:多|尽量多)|越多越好|packed|tight|fast[- ]?paced|hurried|speed", re.I)
_STANDARD = re.compile(r"均衡|适中|标准节奏|正常节奏|moderate|balanced", re.I)


def detect_pace(preferences: Any) -> str:
    """用户没说节奏 → 轻松；明确说“特种兵/紧凑”→ tight；“均衡”→ standard。"轻松/慢游”本来就是 relaxed。"""
    text = str(preferences or "")
    if re.search(r"轻松|慢游|慢节奏|休闲|悠闲|relax|slow|leisure", text, re.I) and not _TIGHT.search(text):
        return RELAXED
    if _TIGHT.search(text):
        return TIGHT
    if _STANDARD.search(text):
        return STANDARD
    return RELAXED


# (关键词, 最短停留分钟)：按顺序匹配，先命中先用。轻松节奏的值；standard 取 80%，tight 不强制。
_SPA = ("spa", "thermal", "terme", "therme", "onsen", "hot spring", "hot springs", "hammam", "温泉", "浴场", "水疗", "泡汤", "bath", "baths", "fürdő", "furdo", "badeschiff")
_THEME = ("amusement", "theme park", "zoo", "aquarium", "disney", "universal", "游乐", "动物园", "水族", "主题乐园", "海洋公园")
_BIG = ("museum", "博物馆", "美术馆", "gallery", "palace", "宫", "castle", "城堡", "fortress", "要塞", "citadel", "monastery", "修道院", "opera", "歌剧")
_MID = ("cathedral", "basilica", "大教堂", "大殿", "synagogue", "会堂", "temple", "寺", "garden", "花园", "park", "公园", "market", "市场", "cave", "洞", "island", "岛")
_QUICK = ("viewpoint", "观景", "lookout", "fountain", "喷泉", "statue", "雕像", "monument", "纪念碑", "bridge", "桥", "gate", "square", "广场", "street", "步行街")
_TYPES = {
    "spa": 210, "turkish_bath": 210, "sauna": 150, "museum": 120, "art_gallery": 100, "castle": 120, "palace": 120,
    "amusement_park": 270, "zoo": 240, "aquarium": 150, "national_park": 180, "botanical_garden": 90, "park": 75,
    "church": 40, "cathedral": 60, "synagogue": 50, "hindu_temple": 45, "buddhist_temple": 45, "place_of_worship": 40,
    "market": 75, "tourist_attraction": 0, "historical_landmark": 60, "monument": 30, "plaza": 30, "bridge": 25,
}


def _has(text: str, words) -> bool:
    return any(w in text for w in words)


def min_stay(name: str = "", category: str = "", primary_type: str = "", pace: str = RELAXED) -> Optional[int]:
    """该地点在当前节奏下的最短停留分钟；没有特别要求返回 None。tight 不强制。"""
    if pace == TIGHT:
        return None
    text = ("%s %s" % (name, category)).lower()
    pt = str(primary_type or "").lower()
    if _has(text, _SPA) or pt in ("spa", "turkish_bath", "sauna"):
        base = 210
    elif _has(text, _THEME) or pt in ("amusement_park", "zoo", "aquarium"):
        base = _TYPES.get(pt) or 240
    elif pt in _TYPES and _TYPES[pt]:
        base = _TYPES[pt]
    elif _has(text, _BIG):
        base = 120
    elif _has(text, _MID):
        base = 60
    elif _has(text, _QUICK):
        base = 30
    else:
        base = 60
    if pace == STANDARD:
        base = int(round(base * 0.8 / 5.0)) * 5 if base >= 100 else base
    return base


def is_spa(name: str = "", category: str = "", primary_type: str = "") -> bool:
    text = ("%s %s" % (name, category)).lower()
    return _has(text, _SPA) or str(primary_type or "").lower() in ("spa", "turkish_bath", "sauna")


def max_sights(pace: str, citywalk: bool = False) -> int:
    if pace == TIGHT:
        return 8
    if citywalk:
        return 6
    return 4 if pace == RELAXED else 5


def pace_block(preferences: Any) -> str:
    p = detect_pace(preferences)
    if p == TIGHT:
        return "\n节奏：用户明确想要紧凑的行程，可多排几个景点，但仍须给每顿饭留足时间、不得时间重叠。\n"
    if p == STANDARD:
        return ("\n节奏：均衡。每天 3–5 个景点，景点之间留出 10–15 分钟机动时间；"
                "温泉/水疗至少 3 小时，博物馆/城堡/宫殿至少 1.5 小时。\n")
    return ("\n节奏：用户没有要求紧凑，默认**轻松自在**。"
            "每天 3–4 个景点（步行漫游类偏好最多 5 个），上午不早于 09:00 开始，晚上不晚于 21:30 结束；"
            "景点之间留 15–30 分钟交通与休息；午餐、晚餐各留 60–90 分钟，不赶时间；"
            "温泉/水疗至少 3.5 小时（当天最多再排 2 个轻量景点）；博物馆/城堡/宫殿至少 2 小时；大教堂、公园、市场 1 小时左右；"
            "观景台、桥、广场 30–45 分钟。宁可少排一个景点，也不要压缩停留时间。\n")
