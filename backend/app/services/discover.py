"""生成前的「主题引导」：先弄清这个目的地“值得为什么而去”，再让用户选择怎么玩。

流程（GET /api/geo/discover）：
  1. 识别目的地的主题标签（最多 3 个，如 Roermond → 购物 / 老城 / 节庆市集）
       优先级：内置知识表（免费、即时）→ 缓存 → 网页搜索摘要 + 一次小模型调用 → 通用兜底
  2. 由**代码**根据天数、城市规模、主标签的“招牌程度”给出系统推荐（模型只负责识别标签，不决定方案）
       deep   主题深度：约 70% 的游玩时间围绕所选主题（1 天 ≈ 6 小时）
       mix    主题 + 精华：约 45% 围绕主题，其余安排当地最有代表性的地方
       sample 精华一览：多处代表性地点，每处停留适中，不做单一主题深挖
  3. 用户选择经 focus_sentence 转成一句约束，追加进 preferences，供策略 / 检索 / 编排统一遵循

安全：标签与细化词只允许白名单字符 + 长度上限（它们会进提示词）；任何失败都回退到通用标签，绝不阻塞生成。
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional

# id → (展示名, 通用细化项)
THEMES: Dict[str, Dict[str, Any]] = {
    "shopping": {"label": "购物", "refine": ["品牌折扣", "本地小店", "伴手礼"]},
    "history": {"label": "历史人文", "refine": ["古迹遗址", "博物馆", "名人故居"]},
    "old_town": {"label": "老城漫游", "refine": ["地标打卡", "小巷咖啡", "拍照出片"]},
    "nature": {"label": "自然风光", "refine": ["徒步", "湖景观景", "公园花园"]},
    "food": {"label": "美食", "refine": ["本地特色", "咖啡甜点", "市集小吃"]},
    "art": {"label": "艺术展览", "refine": ["美术馆", "设计建筑", "街头艺术"]},
    "nightlife": {"label": "夜生活", "refine": ["酒吧小酌", "现场演出", "夜景"]},
    "family": {"label": "亲子乐园", "refine": ["主题乐园", "动物园水族馆", "互动展馆"]},
    "relax": {"label": "温泉休闲", "refine": ["温泉水疗", "公园慢走", "咖啡发呆"]},
    "festival": {"label": "节庆市集", "refine": ["圣诞市集", "当季活动", "手工市集"]},
    "coast": {"label": "海岸海岛", "refine": ["海滩", "游船", "日落"]},
    "sport": {"label": "户外运动", "refine": ["骑行", "滑雪", "水上项目"]},
}

SIGNATURE, STRONG, NORMAL = "signature", "strong", "normal"
_STRENGTH = {SIGNATURE, STRONG, NORMAL}
SIZES = ("small", "medium", "large")

# 内置知识表：别名 → 规模 + 标签。只放“主题非常鲜明”或用户常去的地方；其余交给模型。
KNOWN: Dict[str, Dict[str, Any]] = {}


def _known(aliases: List[str], size: str, *tags: Any) -> None:
    entry = {"size": size, "tags": [dict(zip(("id", "strength", "hint", "rec"), t)) for t in tags]}
    for a in aliases:
        KNOWN[a.lower()] = entry


_known(["鲁尔蒙德", "罗尔蒙德", "roermond"], "small",
       ("shopping", SIGNATURE, "Designer Outlet 与老城商业街，欧洲知名折扣购物地", ["品牌折扣"]),
       ("old_town", NORMAL, "红砖老城、大教堂与默兹河畔，适合购物间隙慢走", []),
       ("festival", NORMAL, "冬季圣诞市集与节庆活动", []))
_known(["布拉格", "prague", "praha"], "medium",
       ("old_town", SIGNATURE, "老城广场、查理大桥与城堡区，一路可串联", ["地标打卡"]),
       ("history", STRONG, "哥特与巴洛克建筑，千年王城", []),
       ("food", NORMAL, "啤酒馆与传统捷克菜", []))
_known(["巴黎", "paris"], "large",
       ("art", SIGNATURE, "卢浮宫、奥赛等世界级博物馆", ["美术馆"]),
       ("old_town", STRONG, "塞纳河畔、蒙马特与玛莱区", []),
       ("shopping", NORMAL, "老佛爷、玛莱区买手店与折扣季", []))
_known(["罗马", "rome", "roma"], "large",
       ("history", SIGNATURE, "斗兽场、万神殿与梵蒂冈，古迹密度极高", ["古迹遗址"]),
       ("food", STRONG, "意面、咖啡与冰淇淋", []),
       ("old_town", NORMAL, "特莱维喷泉与纳沃纳广场一带", []))
_known(["柏林", "berlin"], "large",
       ("history", SIGNATURE, "柏林墙、博物馆岛与冷战遗迹", ["博物馆"]),
       ("art", STRONG, "东区画廊与街头艺术", []),
       ("nightlife", STRONG, "俱乐部与酒吧文化", []))
_known(["慕尼黑", "munich", "münchen", "muenchen"], "large",
       ("food", SIGNATURE, "啤酒花园、白香肠与啤酒节文化", ["本地特色"]),
       ("history", STRONG, "王宫、宁芬堡与老城", []),
       ("nature", NORMAL, "英国花园与阿尔卑斯近郊", []))
_known(["科隆", "cologne", "köln", "koeln"], "medium",
       ("history", SIGNATURE, "科隆大教堂与罗马遗迹", ["古迹遗址"]),
       ("festival", STRONG, "圣诞市集与嘉年华", []),
       ("food", NORMAL, "Kölsch 啤酒与本地小馆", []))
_known(["阿姆斯特丹", "amsterdam"], "medium",
       ("art", SIGNATURE, "国家博物馆、梵高博物馆", ["美术馆"]),
       ("old_town", STRONG, "运河环线与九街区", []),
       ("food", NORMAL, "市集小吃与咖啡馆", []))
_known(["维也纳", "vienna", "wien"], "large",
       ("art", SIGNATURE, "音乐、歌剧与世界级美术馆", ["美术馆"]),
       ("food", STRONG, "老牌咖啡馆与甜点", []),
       ("history", STRONG, "哈布斯堡王朝宫殿", []))
_known(["布达佩斯", "budapest"], "medium",
       ("relax", SIGNATURE, "多瑙河畔的温泉浴场", ["温泉水疗"]),
       ("old_town", STRONG, "城堡山与渔夫堡", []),
       ("nightlife", NORMAL, "废墟酒吧与河上夜景", []))
_known(["东京", "tokyo"], "large",
       ("food", SIGNATURE, "从拉面到怀石的美食之都", ["本地特色"]),
       ("shopping", STRONG, "银座、涩谷、秋叶原各具特色", []),
       ("old_town", NORMAL, "浅草与谷根千老街", []))
_known(["京都", "kyoto"], "medium",
       ("history", SIGNATURE, "千年古寺与神社", ["古迹遗址"]),
       ("old_town", STRONG, "祇园与花见小路", []),
       ("food", NORMAL, "怀石与抹茶甜点", []))
_known(["巴塞罗那", "barcelona"], "large",
       ("art", SIGNATURE, "高迪建筑与毕加索", ["设计建筑"]),
       ("coast", STRONG, "城市海滩", []),
       ("food", STRONG, "Tapas 与海鲜饭", []))
_known(["伦敦", "london"], "large",
       ("history", SIGNATURE, "王室、塔桥与千年古迹", ["博物馆"]),
       ("art", STRONG, "大英博物馆等免费博物馆", []),
       ("shopping", NORMAL, "牛津街与考文特花园", []))


def _norm(s: str) -> str:
    return re.sub(r"[\s·,，、\-_/]+", "", str(s or "")).lower()


_KNOWN_NORM = {_norm(k): v for k, v in KNOWN.items()}


def lookup_known(location: str) -> Optional[Dict[str, Any]]:
    n = _norm(location)
    if not n:
        return None
    if n in _KNOWN_NORM:
        return _KNOWN_NORM[n]
    # “巴黎市”“Prague, Czechia”这类带后缀写法：已知别名是前缀 / 近似包含时命中（别名至少 2 字）
    for k, v in _KNOWN_NORM.items():
        if len(k) >= 2 and (n.startswith(k) or (len(n) <= len(k) + 6 and k in n)):
            return v
    return None


# ───────────── 标签清洗 ─────────────
_SAFE = re.compile(r"[^\w\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af &·+\-]", re.U)


def clean_label(s: Any, limit: int = 12) -> str:
    return _SAFE.sub("", str(s or "")).strip()[:limit].strip()


def clean_labels(items: Any, max_items: int, limit: int = 12) -> List[str]:
    out: List[str] = []
    for x in items if isinstance(items, list) else []:
        t = clean_label(x, limit)
        if t and t not in out:
            out.append(t)
        if len(out) >= max_items:
            break
    return out


def _tag(tid: str, strength: str, hint: str, rec: Optional[List[str]] = None) -> Dict[str, Any]:
    th = THEMES[tid]
    return {"id": tid, "label": th["label"], "strength": strength if strength in _STRENGTH else NORMAL,
            "hint": re.sub(r"\s+", " ", str(hint or "")).strip()[:40], "refine": list(th["refine"]), "rec_refine": list(rec or [])}


def normalize_tags(raw: Any) -> List[Dict[str, Any]]:
    """模型 / 知识表的标签 → 白名单 id + 去重 + 最多 3 个。"""
    out: List[Dict[str, Any]] = []
    seen = set()
    for t in raw if isinstance(raw, list) else []:
        if not isinstance(t, dict):
            continue
        tid = str(t.get("id") or "").strip()
        if tid not in THEMES or tid in seen:
            continue
        seen.add(tid)
        rec = t.get("rec") if isinstance(t.get("rec"), list) else []
        out.append(_tag(tid, str(t.get("strength") or NORMAL), t.get("hint") or "", [r for r in rec if r in THEMES[tid]["refine"]]))
        if len(out) >= 3:
            break
    return out


_PREF_TO_THEME = {"历史文化": "history", "自然风光": "nature", "美食": "food", "购物": "shopping", "艺术": "art", "休闲": "relax"}


def _prefer_order(tags: List[Dict[str, Any]], prefs: List[str]) -> List[Dict[str, Any]]:
    """同样“招牌程度”下，用户已勾选的偏好优先；不改变招牌程度的先后。"""
    want = {_PREF_TO_THEME[p] for p in prefs if p in _PREF_TO_THEME}
    rank = {SIGNATURE: 0, STRONG: 1, NORMAL: 2}
    return sorted(tags, key=lambda t: (rank.get(t["strength"], 2), 0 if t["id"] in want else 1))


GENERIC = [("old_town", NORMAL, "城市最有代表性的街区与地标"), ("food", NORMAL, "当地特色餐饮"), ("history", NORMAL, "历史与人文景点")]


def fallback_tags(prefs: List[str]) -> List[Dict[str, Any]]:
    tags = [_tag(*g) for g in GENERIC]
    for p in prefs:
        tid = _PREF_TO_THEME.get(p)
        if tid and all(t["id"] != tid for t in tags):
            tags[-1] = _tag(tid, NORMAL, "")
    return _prefer_order(tags, prefs)[:3]


# ───────────── 推荐（代码决定） ─────────────
SHARES = {"deep": 70, "mix": 45, "sample": 0}


def recommend(size: str, days: int, tags: List[Dict[str, Any]]) -> Dict[str, Any]:
    """返回 {mode, tags(ids), refine, share, reason}。"""
    days = max(1, int(days or 1))
    size = size if size in SIZES else "medium"
    top = tags[0] if tags else None
    signature = bool(top and top["strength"] == SIGNATURE)
    if not tags:
        mode, reason = "sample", "还没识别出明显主题，建议先看最有代表性的地方"
    elif signature and ((size == "small" and days <= 2) or (size == "medium" and days <= 1)):
        mode, reason = "deep", "这里最出名的是「%s」，只有 %d 天，集中玩透比把它压成顺路一小时更值" % (top["label"], days)
    elif size == "large" and days <= 1:
        mode, reason = "sample", "城市很大而只有 1 天，建议抓最有代表性的几处，不做单一主题"
    elif days <= 3:
        mode, reason = "mix", "%d 天适合围绕「%s」，同时留出时间看当地最有代表性的地方" % (days, top["label"])
    elif size == "small":
        mode, reason = "mix", "小城 %d 天内容容易重复，主题搭配周边精华更丰富" % days
    else:
        mode, reason = "mix", "%d 天时间充裕，主题与精华各占一部分，节奏更均衡" % days
    pick: List[Dict[str, Any]] = []
    if mode == "deep":
        pick = tags[:1] if (size == "small" and days <= 1) or len(tags) < 2 else tags[:2]
    elif mode == "mix":
        pick = tags[:2] if len(tags) >= 2 else tags[:1]
    refine = [r for t in pick for r in t.get("rec_refine", [])][:3]
    return {"mode": mode, "tags": [t["id"] for t in pick], "refine": refine, "share": SHARES[mode], "reason": reason}


def mode_options(days: int, rec: Dict[str, Any]) -> List[Dict[str, Any]]:
    hours = round(9 * SHARES["deep"] / 100.0 * 2) / 2
    return [
        {"id": "deep", "label": "主题深度", "desc": "约 %d%% 的游玩时间（一天约 %g 小时）围绕所选主题，其余只留用餐与顺路小景" % (SHARES["deep"], hours), "recommended": rec["mode"] == "deep"},
        {"id": "mix", "label": "主题 + 精华", "desc": "约 %d%% 围绕主题，其余安排当地最有代表性的地方" % SHARES["mix"], "recommended": rec["mode"] == "mix"},
        {"id": "sample", "label": "精华一览", "desc": "多处代表性地点，每处停留适中，不做单一主题深挖", "recommended": rec["mode"] == "sample"},
    ]


# ───────────── 把用户选择变成一句约束 ─────────────
def sanitize_focus(focus: Any) -> Optional[Dict[str, Any]]:
    """入口清洗：返回干净的 focus 或 None。"""
    if not focus:
        return None
    g = (lambda k: focus.get(k)) if isinstance(focus, dict) else (lambda k: getattr(focus, k, None))
    mode = str(g("mode") or "")
    if mode not in ("deep", "mix", "sample"):
        return None
    tags = clean_labels(g("tags"), 3)
    if mode != "sample" and not tags:
        return None
    return {"mode": mode, "tags": tags if mode != "sample" else [], "refine": clean_labels(g("refine"), 4)}


def focus_sentence(focus: Any, days: int = 1) -> str:
    """无有效内容返回空串。措辞避开节奏 / 步行关键词（见 pace.py、itinerary_utils._is_citywalk_preference），以免误触“紧凑”或“城市漫步”。"""
    f = sanitize_focus(focus)
    if not f:
        return ""
    days = max(1, int(days or 1))
    if f["mode"] == "sample":
        return "；【精华一览】覆盖当地最具代表性的地点，每处停留适中，行程节奏轻松自在，不做单一主题深挖"
    names = "、".join("「%s」" % t for t in f["tags"])
    detail = ("；细化方向：" + "、".join(f["refine"])) if f["refine"] else ""
    if f["mode"] == "deep":
        return ("；【主题深度】本次旅行以%s为主体：约 %d%% 的游玩时间围绕它展开，主体时段连续不少于 %s，集中在该主题最核心的地点，"
                "不要只把它当成顺路的一小时；其余时间只安排用餐与少量顺路小景，整体轻松自在%s") % (names, SHARES["deep"], "5 小时" if days <= 1 else "半天", detail)
    return "；【主题 + 精华】约 %d%% 的游玩时间围绕%s，其余安排当地最有代表性的地方，整体轻松自在%s" % (SHARES["mix"], names, detail)


# ───────────── 模型识别（未知目的地） ─────────────
CACHE_TTL = 14 * 86400
_cache_lock = threading.Lock()
_mem: Dict[str, Any] = {}


def _cache_path() -> Path:
    return Path(os.getenv("EZTRIP_DISCOVER_CACHE", "")) if os.getenv("EZTRIP_DISCOVER_CACHE") else Path(__file__).resolve().parents[2] / "storage" / "discover_cache.json"


def _cache_load() -> Dict[str, Any]:
    with _cache_lock:
        if _mem.get("loaded"):
            return _mem["data"]
        try:
            raw = json.loads(_cache_path().read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            raw = {}
        _mem.update(loaded=True, data=raw if isinstance(raw, dict) else {})
        return _mem["data"]


def cache_get(location: str) -> Optional[Dict[str, Any]]:
    v = _cache_load().get(_norm(location))
    if isinstance(v, dict) and time.time() - float(v.get("t") or 0) < CACHE_TTL:
        return {"size": v.get("size") if v.get("size") in SIZES else "medium", "tags": normalize_tags(v.get("tags"))}
    return None


def cache_put(location: str, size: str, tags: List[Dict[str, Any]]) -> None:
    data = _cache_load()
    with _cache_lock:
        data[_norm(location)] = {"t": time.time(), "size": size, "tags": tags}
        if len(data) > 400:  # 简单上限：丢最旧的
            for k in sorted(data, key=lambda k: data[k].get("t", 0))[:100]:
                data.pop(k, None)
        try:
            p = _cache_path()
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            tmp.replace(p)
        except Exception:  # noqa: BLE001
            pass


PROMPT = (
    "你是旅行目的地分析师。根据目的地和（可能为空的）网页搜索摘要，判断这个地方「值得为什么而去」。\n"
    "只输出 JSON：{\"size\":\"small|medium|large\",\"tags\":[{\"id\":\"...\",\"strength\":\"signature|strong|normal\",\"hint\":\"...\"}]}\n"
    "规则：\n"
    "1. tags 最多 3 个，按重要性排序；id 只能取：" + "、".join(THEMES) + "。\n"
    "2. size：small=小城镇 / 单一园区，一天能逛完主要内容；medium=中等城市，2-3 天；large=大都市，需要 4 天以上。\n"
    "3. strength：signature=这里最出名、人们专程为它而来（最多 1 个）；strong=很突出；normal=值得顺带。\n"
    "4. hint：一句话（≤25 字，中文）写出这个地方在该主题上的具体内容（地名/特色），不要空话。\n"
    "5. 把握不大时给通用标签，hint 写该类目的通用看点，不要编造，也不要出现“信息较少 / 建议查看官网”之类表述；不要输出 JSON 以外的文字。"
)


def _parse_json(text: str) -> Dict[str, Any]:
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return {}
    try:
        v = json.loads(m.group(0))
        return v if isinstance(v, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def web_context(location: str) -> str:
    """用 local_events MCP 的 web_search 取几条摘要；任何失败返回空串。同步函数，调用方放线程里。"""
    try:
        from . import fun_chat as fc
        if not fc.mcp_available() or os.getenv("EZTRIP_DISCOVER_SEARCH", "1") == "0":
            return ""
        res = fc.call_mcp("web_search", {"query": "%s travel what to do known for top attractions shopping" % location[:40]})
        items = (res.get("results") or [])[:5]
        return "\n".join("- %s：%s" % (fc._clip(i.get("title"), 80), fc._clip(i.get("snippet"), 160)) for i in items)  # noqa: SLF001
    except Exception as e:  # noqa: BLE001
        print("[discover] web context failed %s" % type(e).__name__)
        return ""


Complete = Callable[[List[Dict[str, str]]], Awaitable[str]]


async def identify(location: str, complete: Complete, context: str = "") -> Optional[Dict[str, Any]]:
    """调模型识别标签；失败返回 None。"""
    user = "目的地：%s\n网页摘要：\n%s" % (clean_label(location, 40) or location[:40], context or "（无）")
    try:
        raw = await complete([{"role": "system", "content": PROMPT}, {"role": "user", "content": user}])
    except Exception as e:  # noqa: BLE001
        print("[discover] model failed %s" % type(e).__name__)
        return None
    obj = _parse_json(raw)
    tags = normalize_tags(obj.get("tags"))
    if not tags:
        return None
    return {"size": obj.get("size") if obj.get("size") in SIZES else "medium", "tags": tags}


def build(location: str, days: int, size: str, tags: List[Dict[str, Any]], prefs: List[str], source: str) -> Dict[str, Any]:
    tags = _prefer_order(tags, prefs)[:3]
    rec = recommend(size, days, tags)
    return {"location": location, "size": size, "tags": tags, "modes": mode_options(days, rec), "recommended": rec, "source": source}


def known_tags(location: str) -> Optional[Dict[str, Any]]:
    k = lookup_known(location)
    if not k:
        return None
    return {"size": k["size"], "tags": normalize_tags(k["tags"])}
