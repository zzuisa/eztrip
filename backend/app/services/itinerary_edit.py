"""行程编辑的纯逻辑（无 IO，便于单测）：校验/清洗用户提交的行程、时间推算、AI 提案的解析与 diff。

数据形态沿用 payload.itinerary：每天 {day, title, activities[], meals[], ...}。
- 用户提交（PUT）只允许改 activities / meals，其余字段（标题、描述、交通…）保持不变。
- 每个条目只接受白名单字段并裁剪长度，不信任客户端传来的任何结构。
"""

from __future__ import annotations

import copy
import json
import re
from typing import Any, Dict, List, Optional, Tuple

from . import voice as _voice

MAX_ACTIVITIES = 20
MAX_MEALS = 10
MAX_BODY_BYTES = 400_000
MEAL_TYPES = ("breakfast", "lunch", "dinner", "snack")
MEAL_DEFAULT_START = {"breakfast": 8 * 60, "lunch": 12 * 60 + 30, "dinner": 18 * 60 + 30, "snack": 15 * 60}

_ACT_TEXT = {"name": 120, "time": 30, "address": 200, "description": 800, "route_desc": 400, "preference_reason": 200}
_MEAL_TEXT = {"name": 120, "time": 30, "address": 200, "description": 800, "route_desc": 400}
_IMG_KEYS = ("image_url", "photo_url", "thumbnail", "image")
_TIME_RE = re.compile(r"(\d{1,2}):(\d{2})")


class EditError(ValueError):
    """用户提交的内容不合法（转成 422）。"""


def clip(v: Any, n: int) -> str:
    return re.sub(r"[ \t\r\f\v]+", " ", str(v if v is not None else "")).strip()[:n]


def _num(v: Any, lo: float, hi: float) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f or f < lo or f > hi:
        return None
    return f


def _safe_url(v: Any) -> str:
    s = str(v or "").strip()
    if len(s) > 600 or s.startswith("data:"):
        return ""
    return s if (s.startswith("/") and not s.startswith("//")) or s.startswith("https://") else ""


# ---------------------------------------------------------------- 时间


def parse_range(text: Any) -> Tuple[Optional[int], Optional[int]]:
    ms = _TIME_RE.findall(str(text or ""))
    if not ms:
        return None, None
    start = int(ms[0][0]) * 60 + int(ms[0][1])
    end = int(ms[1][0]) * 60 + int(ms[1][1]) if len(ms) > 1 else None
    return start, (end if end is not None and end > start else None)


def fmt_minutes(m: int) -> str:
    m = max(0, min(int(m), 23 * 60 + 59))
    return "%02d:%02d" % (m // 60, m % 60)


def fmt_range(start: int, end: Optional[int]) -> str:
    return fmt_minutes(start) + ("-" + fmt_minutes(end) if end else "")


def item_start(item: Dict[str, Any], is_meal: bool) -> int:
    s, _ = parse_range(item.get("time"))
    if s is not None:
        return s
    return MEAL_DEFAULT_START.get(str(item.get("type")), 12 * 60) if is_meal else 9 * 60


# ---------------------------------------------------------------- 清洗


def _clean_item(raw: Any, is_meal: bool, base: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not isinstance(raw, dict):
        return None
    name = clip(raw.get("name"), 120)
    if not name:
        return None
    out: Dict[str, Any] = copy.deepcopy(base) if base else {}
    spec = _MEAL_TEXT if is_meal else _ACT_TEXT
    for k, n in spec.items():
        if k in raw:
            out[k] = clip(raw.get(k), n)
    out["name"] = name
    if is_meal:
        t = str(raw.get("type") or out.get("type") or "snack")
        out["type"] = t if t in MEAL_TYPES else "snack"
        cost = _num(raw.get("estimated_cost", out.get("estimated_cost", 0)), 0, 100000)
        out["estimated_cost"] = cost if cost is not None else 0.0
    else:
        price = _num(raw.get("ticket_price", out.get("ticket_price", 0)), 0, 100000)
        out["ticket_price"] = price if price is not None else 0.0
        if "preference_matched" in raw:
            out["preference_matched"] = bool(raw.get("preference_matched"))
    lat, lng = _num(raw.get("latitude"), -90, 90), _num(raw.get("longitude"), -180, 180)
    if lat is not None and lng is not None:
        out["latitude"], out["longitude"] = lat, lng
    elif "latitude" in raw or "longitude" in raw:
        out.pop("latitude", None)
        out.pop("longitude", None)
    rating = _num(raw.get("rating"), 0, 5)
    if rating is not None:
        out["rating"] = rating
    for k in _IMG_KEYS:
        if k in raw:
            u = _safe_url(raw.get(k))
            if u:
                out[k] = u
            else:
                out.pop(k, None)
    if raw.get("user_added") or raw.get("ai_added"):
        out["user_added" if raw.get("user_added") else "ai_added"] = True
    out.setdefault("time", "")
    out.setdefault("address", "")
    out.setdefault("description", "")
    return out


def _index_old(itinerary: List[Dict[str, Any]]) -> Dict[Tuple[bool, str], Dict[str, Any]]:
    idx: Dict[Tuple[bool, str], Dict[str, Any]] = {}
    for d in itinerary:
        for a in d.get("activities") or []:
            if isinstance(a, dict) and a.get("name"):
                idx.setdefault((False, str(a["name"])), a)
        for m in d.get("meals") or []:
            if isinstance(m, dict) and m.get("name"):
                idx.setdefault((True, str(m["name"])), m)
    return idx


def apply_days(itinerary: List[Dict[str, Any]], submitted: Any) -> List[Dict[str, Any]]:
    """把提交的各天 activities/meals 并入 itinerary，返回新 itinerary（不修改入参）。

    要求天数与现有一致；同一天内不得出现同名（同类）条目；其余字段保持原样。
    """
    if not isinstance(submitted, list) or len(submitted) != len(itinerary):
        raise EditError("天数与现有行程不一致")
    if len(json.dumps(submitted, ensure_ascii=False)) > MAX_BODY_BYTES:
        raise EditError("提交内容过大")
    old_idx = _index_old(itinerary)
    result: List[Dict[str, Any]] = []
    for i, (day, sub) in enumerate(zip(itinerary, submitted)):
        if not isinstance(sub, dict):
            raise EditError("Day %d 数据格式错误" % (i + 1))
        acts_in, meals_in = sub.get("activities") or [], sub.get("meals") or []
        if not isinstance(acts_in, list) or not isinstance(meals_in, list):
            raise EditError("Day %d 数据格式错误" % (i + 1))
        if len(acts_in) > MAX_ACTIVITIES or len(meals_in) > MAX_MEALS:
            raise EditError("Day %d 的条目过多（景点 ≤ %d，餐饮 ≤ %d）" % (i + 1, MAX_ACTIVITIES, MAX_MEALS))
        acts, meals, seen = [], [], set()
        for raw in acts_in:
            it = _clean_item(raw, False, old_idx.get((False, clip(raw.get("name") if isinstance(raw, dict) else "", 120))))
            if it is None:
                continue
            if it["name"] in seen:
                raise EditError("Day %d 已有同名地点「%s」" % (i + 1, it["name"]))
            seen.add(it["name"])
            acts.append(it)
        for raw in meals_in:
            it = _clean_item(raw, True, old_idx.get((True, clip(raw.get("name") if isinstance(raw, dict) else "", 120))))
            if it is None:
                continue
            if it["name"] in seen:
                raise EditError("Day %d 已有同名地点「%s」" % (i + 1, it["name"]))
            seen.add(it["name"])
            meals.append(it)
        nd = dict(day)
        nd["activities"], nd["meals"] = acts, meals
        result.append(nd)
    return result


def needs_geocode(itinerary: List[Dict[str, Any]]) -> List[Tuple[int, bool, int]]:
    """返回缺少坐标的条目位置 (day_idx, is_meal, idx)。"""
    out = []
    for di, d in enumerate(itinerary):
        for ai, a in enumerate(d.get("activities") or []):
            if "latitude" not in a or "longitude" not in a:
                out.append((di, False, ai))
        for mi, m in enumerate(d.get("meals") or []):
            if "latitude" not in m or "longitude" not in m:
                out.append((di, True, mi))
    return out


# ---------------------------------------------------------------- AI 编辑：上下文与提案


def ordered_items(day: Dict[str, Any]) -> List[Dict[str, Any]]:
    """一天内的条目按展示顺序（开始时间）排好：[{ref_kind, idx, item}]。"""
    rows = []
    for i, a in enumerate(day.get("activities") or []):
        if isinstance(a, dict) and a.get("name"):
            rows.append((item_start(a, False), 0, i, {"is_meal": False, "idx": i, "item": a}))
    for i, m in enumerate(day.get("meals") or []):
        if isinstance(m, dict) and m.get("name"):
            rows.append((item_start(m, True), 1, i, {"is_meal": True, "idx": i, "item": m}))
    rows.sort(key=lambda r: (r[0], r[1], r[2]))
    return [r[3] for r in rows]


def build_refs(itinerary: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """ref 形如 D2.3（第 2 天按时间顺序第 3 项）。"""
    refs: Dict[str, Dict[str, Any]] = {}
    for di, d in enumerate(itinerary):
        for n, row in enumerate(ordered_items(d), 1):
            refs["D%d.%d" % (di + 1, n)] = {"day": di, **row}
    return refs


def describe_itinerary(payload: Dict[str, Any], refs: Dict[str, Dict[str, Any]], focus_days: List[int]) -> str:
    cur = str(payload.get("budget_currency") or (payload.get("total_budget") or {}).get("currency") or "EUR")
    lines = ["目的地：%s，共 %d 天（货币 %s）。" % (clip(payload.get("location"), 40), len(payload.get("itinerary") or []), cur)]
    from .weather import planning_block
    lines.append(planning_block(payload.get('weather')))
    pref = clip(payload.get("request_preferences"), 200)
    if pref:
        lines.append("旅行者最初的偏好：" + pref)
    for di, d in enumerate(payload.get("itinerary") or []):
        mark = "（可修改）" if di in focus_days else "（仅供参考，除非必须不要动）"
        lines.append("\n第%d天「%s」%s" % (di + 1, clip(d.get("title"), 30), mark))
        for ref, r in refs.items():
            if r["day"] != di:
                continue
            it = r["item"]
            kind = "餐饮/" + str(it.get("type") or "") if r["is_meal"] else "景点"
            cost = it.get("estimated_cost") if r["is_meal"] else it.get("ticket_price")
            lines.append("  %s [%s] %s | %s | 费用 %s | %s" % (
                ref, kind, clip(it.get("name"), 60), clip(it.get("time"), 20) or "未定", cost if cost is not None else "?", clip(it.get("description"), 60),
            ))
    return "\n".join(lines)[:7000]


SYSTEM_PROMPT = (
    "你是旅行行程编辑助手。用户会对一份已有行程提出修改要求（换地点、调整节奏、省预算、加/删景点、改顺序等）。"
    "你输出对行程的修改结果，只输出一个 JSON 对象，不要解释、不要代码块：\n"
    '{"summary":"一句话说明改了什么及理由(≤60字)","days":[{"day":1,"items":[...]}]}\n'
    "规则：\n"
    "1) days 只包含你实际要修改的天，且只能是“可修改”的天；每个 day 的 items 是这一天修改后的完整、按时间先后排序的清单。\n"
    '2) 保留原有地点：{"ref":"D1.2"} 可附带 "time"（新的时间，如 "10:00-11:30"）和 "description"（仅在需要时改）。ref 必须来自给定清单，且整份输出里每个 ref 至多出现一次。\n'
    '3) 新增/替换的地点：{"ref":null,"kind":"attraction"或"meal","meal_type":"breakfast|lunch|dinner|snack"(仅餐饮),"name":"真实存在的地点名(尽量用当地通用名称)",'
    '"search":"用于地图检索的关键词，含地点名和所在片区","time":"09:00-10:30","description":"一句话理由/亮点(≤60字)","cost":数字(预估费用，当地货币，未知填0)}。\n'
    "4) 清单里没出现在 days 里的原有地点，在被修改的那几天里视为删除；因此不想删的地点必须写出来。\n"
    "5) 同一天的时间不得重叠，景点之间留出合理的交通时间；餐饮放在合适的时段；默认保持轻松自在（每天 3–4 个景点，除非用户要求紧凑）：温泉/水疗至少 3.5 小时，博物馆/城堡/宫殿至少 2 小时，景点之间留 15 分钟以上机动时间；一天景点不超过 8 个。\n"
    "6) 不要编造不存在的店名；不确定时选知名、评价稳定的地点。费用只是估计。\n"
    "7) 如果用户要求与行程无关或无法完成，返回 {\"summary\":\"说明原因\",\"days\":[]}。\n"
    "8) summary 与 description 用专业顾问的口吻：先说改了什么、带来什么好处，用肯定句，不写“信息较少 / 建议查看官网 / 以官方为准”，不提及 AI。"
)


def build_messages(payload: Dict[str, Any], refs: Dict[str, Dict[str, Any]], focus_days: List[int], instruction: str, target_ref: Optional[str]) -> List[Dict[str, str]]:
    user = [describe_itinerary(payload, refs, focus_days)]
    if target_ref:
        it = refs[target_ref]["item"]
        user.append("\n用户选中的地点：%s（%s）。只改动这个地点（可替换/调整时间/改描述），其余地点保持不变，但可为配合它而微调时间。" % (clip(it.get("name"), 60), target_ref))
    user.append("\n用户要求：" + clip(instruction, 400))
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": "\n".join(user)}]


def extract_json(content: str) -> Optional[Dict[str, Any]]:
    m = re.search(r"\{.*\}", content or "", flags=re.S)
    if not m:
        return None
    try:
        raw = json.loads(m.group(0))
    except Exception:  # noqa: BLE001
        return None
    return raw if isinstance(raw, dict) else None


def _fix_times(items: List[Dict[str, Any]], is_meal_flags: List[bool]) -> None:
    """保证同一天时间先后递增、不重叠；缺失的时间按“上一项结束 + 15 分钟”补。"""
    prev_start, prev_end = None, None
    for it, is_meal in zip(items, is_meal_flags):
        s, e = parse_range(it.get("time"))
        dur = (e - s) if (s is not None and e) else (60 if is_meal else 90)
        if s is None or (prev_end is not None and s < prev_end):
            s = (prev_end + 15) if prev_end is not None else item_start(it, is_meal)
        it["time"] = fmt_range(s, s + dur) if e else fmt_minutes(s)
        prev_start, prev_end = s, s + dur


class ProposalError(ValueError):
    pass


def parse_proposal(content: str, payload: Dict[str, Any], refs: Dict[str, Dict[str, Any]], focus_days: List[int], target_ref: Optional[str]) -> Dict[str, Any]:
    """校验 LLM 输出，返回中间提案：{summary, days:[{day_idx, slots:[{ref|None, ...}]}]}。新地点尚未定位。"""
    raw = extract_json(content)
    if raw is None:
        raise ProposalError("输出格式不合格")
    summary = clip(_voice.scrub_text(raw.get("summary")), 120)
    days_out: List[Dict[str, Any]] = []
    used: set = set()
    for d in raw.get("days") or []:
        if not isinstance(d, dict):
            continue
        try:
            di = int(d.get("day")) - 1
        except (TypeError, ValueError):
            continue
        if di not in focus_days or any(x["day_idx"] == di for x in days_out):
            continue
        slots = []
        for it in (d.get("items") or [])[: MAX_ACTIVITIES + MAX_MEALS]:
            if not isinstance(it, dict):
                continue
            ref = it.get("ref")
            if ref:
                ref = str(ref)
                if ref not in refs or ref in used:
                    continue
                used.add(ref)
                slots.append({"ref": ref, "time": clip(it.get("time"), 30), "description": clip(_voice.scrub_text(it.get("description")), 300) if it.get("description") else ""})
            else:
                name = clip(it.get("name"), 120)
                if not name:
                    continue
                kind = "meal" if str(it.get("kind")) == "meal" else "attraction"
                mt = str(it.get("meal_type") or "")
                slots.append({
                    "ref": None, "kind": kind, "meal_type": mt if mt in MEAL_TYPES else ("lunch" if kind == "meal" else ""),
                    "name": name, "search": clip(it.get("search"), 160) or name, "time": clip(it.get("time"), 30),
                    "description": clip(_voice.scrub_text(it.get("description")), 300), "cost": _num(it.get("cost"), 0, 100000) or 0.0,
                })
        days_out.append({"day_idx": di, "slots": slots})
    if not days_out and not summary:
        raise ProposalError("没有给出修改")
    if target_ref:
        tday = refs[target_ref]["day"]
        for dd in days_out:
            if dd["day_idx"] != tday:
                raise ProposalError("修改超出了所选地点所在的那一天")
        day_refs = {r for r, v in refs.items() if v["day"] == tday and r != target_ref}
        got = {s["ref"] for dd in days_out for s in dd["slots"] if s["ref"]}
        if days_out and not day_refs <= got:
            raise ProposalError("改动了所选地点以外的内容")
    return {"summary": summary, "days": days_out}


def assemble(payload: Dict[str, Any], refs: Dict[str, Dict[str, Any]], proposal: Dict[str, Any], located: Dict[Tuple[int, int], Dict[str, Any]]) -> Dict[str, Any]:
    """把中间提案落成最终各天 activities/meals，并生成变更清单。

    located[(day_idx, slot_idx)] = 地图检索结果 {name, address, latitude, longitude, rating, ...}（可缺）。
    """
    itinerary = payload.get("itinerary") or []
    out_days, changes, warnings = [], [], []
    out_day_idx = {dd["day_idx"] for dd in proposal["days"]}
    used_refs = {s["ref"] for dd in proposal["days"] for s in dd["slots"] if s["ref"]}

    for dd in proposal["days"]:
        di = dd["day_idx"]
        acts: List[Dict[str, Any]] = []
        meals: List[Dict[str, Any]] = []
        ordered: List[Dict[str, Any]] = []
        flags: List[bool] = []
        for si, s in enumerate(dd["slots"]):
            if s["ref"]:
                r = refs[s["ref"]]
                it = copy.deepcopy(r["item"])
                if s.get("description"):
                    it["description"] = s["description"]
                if s.get("time"):
                    it["time"] = s["time"]
                is_meal = r["is_meal"]
                src_time = r["item"].get("time")
            else:
                loc = located.get((di, si)) or {}
                is_meal = s["kind"] == "meal"
                it = {"name": loc.get("name") or s["name"], "time": s.get("time") or "", "address": loc.get("address") or "", "description": s.get("description") or loc.get("summary") or "", "ai_added": True}
                if loc.get("latitude") is not None and loc.get("longitude") is not None:
                    it["latitude"], it["longitude"] = float(loc["latitude"]), float(loc["longitude"])
                else:
                    warnings.append("「%s」未能在地图上定位，请确认后再应用" % it["name"])
                if loc.get("rating") is not None:
                    it["rating"] = loc["rating"]
                if is_meal:
                    it["type"] = s["meal_type"] or "lunch"
                    it["estimated_cost"] = s["cost"]
                else:
                    it["ticket_price"] = s["cost"] if s["cost"] else float(loc.get("ticket_price") or 0)
                src_time = None
            ordered.append(it)
            flags.append(is_meal)
        _fix_times(ordered, flags)
        seen_names: set = set()
        for it, is_meal in zip(ordered, flags):
            if it["name"] in seen_names:
                continue
            seen_names.add(it["name"])
            (meals if is_meal else acts).append(it)
        out_days.append({"day": di + 1, "activities": acts, "meals": meals})

    # 变更清单
    final = {od["day"] - 1: {x["name"]: x for x in od["activities"] + od["meals"]} for od in out_days}
    new_pos: Dict[str, Tuple[int, Dict[str, Any]]] = {}
    for dd in proposal["days"]:
        for s in dd["slots"]:
            if s["ref"]:
                new_pos[s["ref"]] = (dd["day_idx"], s)
    for ref, r in refs.items():
        if r["day"] not in out_day_idx and ref not in used_refs:
            continue
        it = r["item"]
        kind = "meal" if r["is_meal"] else "attraction"
        if ref not in used_refs:
            changes.append({"type": "remove", "day": r["day"] + 1, "name": it.get("name"), "kind": kind})
            continue
        nd, slot = new_pos[ref]
        if nd != r["day"]:
            changes.append({"type": "move", "day": nd + 1, "from_day": r["day"] + 1, "name": it.get("name"), "kind": kind})
            continue
        fin = final.get(nd, {}).get(it.get("name"))
        if fin and clip(fin.get("time"), 30) != clip(it.get("time"), 30):
            changes.append({"type": "retime", "day": nd + 1, "name": it.get("name"), "from": clip(it.get("time"), 30), "to": fin.get("time"), "kind": kind})
        elif slot.get("description"):
            changes.append({"type": "edit", "day": nd + 1, "name": it.get("name"), "kind": kind})
    for od in out_days:
        for it in od["activities"] + od["meals"]:
            if it.get("ai_added"):
                changes.append({"type": "add", "day": od["day"], "name": it["name"], "time": it.get("time"), "kind": "meal" if "type" in it else "attraction", "note": it.get("description", "")})

    # 被移到“可修改天”里的条目，其原所在天若不在输出里，需要同步去掉（避免重复）
    for day_n in {c["from_day"] for c in changes if c["type"] == "move" and (c["from_day"] - 1) not in out_day_idx}:
        di = day_n - 1
        d = itinerary[di]
        moved_away = {refs[r]["item"].get("name") for r in used_refs if refs[r]["day"] == di}
        out_days.append({
            "day": day_n,
            "activities": [a for a in d.get("activities") or [] if a.get("name") not in moved_away],
            "meals": [m for m in d.get("meals") or [] if m.get("name") not in moved_away],
        })
    out_days.sort(key=lambda x: x["day"])
    return {"summary": proposal["summary"], "days": out_days, "changes": changes, "warnings": warnings}

