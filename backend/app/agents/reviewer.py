"""Critic（行程审核）：多天行程生成后，由独立模型对整趟行程做一次一致性审核。

对应 agent-config 里的 critic 角色（routes.yaml: validation → critic，“检查时间、预算、路线和工具结果的一致性”）。
默认模型 combo/main（LiteLLM 别名 ocx-main），站长可在“模型设置”里改（角色 review）。

原则：
- 只在多天行程（days >= min_days，默认 2）时运行；单日行程不审。
- 先由代码算好客观数据（相邻景点距离、当天跨度、跨天重复）再交给模型，模型不用自己算坐标。
- 失败不拖垮规划（failure_mode: report_and_continue）：审核超时/出错 → 跳过并记录 status。
- 模型只给“问题 + 改法”，不改行程；由 refine.py 组织“审核 → 带着意见重排 → 复审”的闭环（最多 max_rounds 轮），
  直到没有中/高问题或评分达标；用户最终看到的是修订后的行程，只有闭环后仍存在的硬伤才会作为提醒展示。
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from ..services.pace import detect_pace
from typing import Any, Dict, List, Optional

from ..agent_config import agent as agent_cfg
from ..services.day_geo import _coord, haversine_km
from ..services.itinerary_utils import _ensure_list, _extract_json_object
from ..services import voice

log = logging.getLogger(__name__)

ISSUE_TYPES = {"geography", "pacing", "timing", "meal", "duplicate", "theme", "budget", "season"}
REVISABLE = {"pacing", "timing", "meal", "theme", "duplicate", "geography"}   # 带着意见让 composer 重排能解决的类型
NOT_SHOWN = {"season", "budget"}   # 不作为“提醒”展示：预算由代码汇总；季节提示进入出行提示
SEVERITIES = ("high", "medium", "low")

_SYSTEM = (
    "你是严格的旅行行程审核员。只根据给定数据指出真实存在的问题，不编造营业时间、票价或地点；"
    "距离数据已由程序算好，直接使用。输出必须是纯 JSON。\n"
    + voice.VOICE_NOTICE
    + '核对游玩结构与用户偏好；非人文深度行程避免同日多个展馆、连续多天只有古迹。半天体验允许只有1–2个活动。季节娱乐要核实日期、天气、装备、预约和往返时间，不因追求多样性硬塞滑雪或温泉。'
)

_PACE_RULES = {
    "relaxed": ("用户没有要求紧凑，行程应当**轻松自在**：每天以 3–4 个景点 + 三餐为宜，景点之间应留 15 分钟以上的交通/休息；"
                "温泉/水疗少于 3.5 小时、博物馆/宫殿/城堡少于 2 小时、午晚餐少于 60 分钟，或一天排了 5 个以上景点、上午 09:00 前开始，都属于“过紧”（medium）；"
                "景点太少导致大段空档才算“过空”；"),
    "standard": "每天景点数量/节奏是否过密或过空（正常 3–5 个景点 + 三餐），是否把长时间景点塞进很短的时段（温泉/水疗应不少于 3 小时）；",
    "tight": "用户明确要紧凑行程，可接受较多景点；只在时间重叠、餐饮被挤掉或明显赶不上时才算问题；",
}

_TEMPLATE = """请审核「{location}」的 {days} 天行程。{round_note}
旅行者：偏好「{preferences}」；交通偏好「{transport}」；出发地「{origin}」；日期「{dates}」。

逐天数据（legs_km 是相邻景点的直线距离 km，span_km 是当天最远两点的距离）：
{plan_json}

程序已发现的问题（不要重复）：{known}

请检查：
1. geography：一天内是否跨越过远的区域（span_km 过大、legs_km 里有大跳跃），或整趟是否不在同一城市；
2. pacing：{pace_rule}
3. timing：时间段是否重叠、顺序是否倒置、用餐时间是否不合理、夜间是否排了景点；
4. meal：是否缺餐、午晚餐名称重复、餐厅明显离当天路线很远；
5. duplicate：同一地点或同类连锁在多天重复；
6. theme：与用户偏好是否严重不符（如偏好美食却几乎没有餐饮亮点）；
7. budget：预算是否明显不合理；
8. season：给定日期下的明显季节/节假日风险（只提醒，severity 用 low，不要断言具体营业时间）。

只输出如下 JSON，issues 最多 8 条，无问题时 issues 为空数组：
{{"score":0到100的整数,"summary":"一句话总评（中文，不超过40字）",
"issues":[{{"day":1,"severity":"high|medium|low","type":"geography|pacing|timing|meal|duplicate|theme|budget|season",
"message":"给用户看的一句话（中文，不超过60字，不要出现“AI”字样）","fix":"给编排器的具体修改要求（中文，不超过80字）"}}]}}
每个 high / medium 问题都必须给出可执行的 fix（说明具体怎么改，例如“晚餐挪到 18:30 之后”“把重复的午餐换成别的餐厅”“去掉远离主路线的景点”）。
day 为 0 表示针对整趟行程。severity=high 仅用于必须修改的硬伤；medium 只用于明显影响体验的问题；轻微的衔接/节奏意见用 low；同类问题合并成一条，不要逐天重复。"""


_FACTS = ("\n以上就是用户最终会拿到的行程：到达/返程/取还车手续已经由程序算进每天的 day_start_transit / day_end_transit，"
          "window 是用户给的旅途时间窗：第一天指最早出发时间、最后一天指最晚到家（含还车）时间，不是景点游览时间；sunset 是当地日落。这些交通与时间都是已排定的事实，"
          "不要再报告“缺少取还车/返程/到达时间”这类已有数据的问题；只在数据里确实冲突（如晚于 window、日落后才开始户外、返程过晚）时才提 timing 问题。")


def settings() -> Dict[str, Any]:
    c = agent_cfg("critic")
    def _i(key: str, default: int) -> int:
        try:
            return max(0, int(c.get(key, default)))
        except (TypeError, ValueError):
            return default
    return {"min_days": max(1, _i("min_days", 1)), "max_revisions": _i("max_revisions", 6),
            "timeout_seconds": max(10, _i("timeout_seconds", 90)),
            "max_rounds": min(4, _i("max_rounds", 2)), "target_score": min(100, _i("target_score", 85)),
            "total_timeout_seconds": max(30, _i("total_timeout_seconds", 200))}


def should_review(days: int) -> bool:
    return int(days) >= 8 or int(days) >= settings()["min_days"]


def _legs(points: List[tuple]) -> List[float]:
    return [round(haversine_km(a, b), 1) for a, b in zip(points, points[1:])]


def build_plan_view(itinerary: List[Dict[str, Any]], meta: Optional[Dict[str, Any]] = None,
                    weather: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """把行程压成审核员需要的紧凑结构，并由代码算好距离。
    meta/weather 给了就把“最终事实”一并带上：每日可游览窗口、首/末交通（含取还车手续、出发/到达时间）、日落。"""
    from ..services import finalize as fin
    wins = fin.windows(meta or {})
    wdays = (weather or {}).get("days") or []
    out: List[Dict[str, Any]] = []
    for day in itinerary:
        acts = [a for a in _ensure_list(day.get("activities")) if isinstance(a, dict)]
        pts = [c for c in (_coord(a) for a in acts) if c]
        span = max((haversine_km(a, b) for i, a in enumerate(pts) for b in pts[i + 1:]), default=0.0)
        out.append({
            "day": int(day.get("day") or len(out) + 1),
            "title": str(day.get("title") or "")[:40],
            "activities": [{"name": str(a.get("name") or "")[:40], "time": str(a.get("time") or ""),
                            "ticket": a.get("ticket_price") or 0} for a in acts],
            "meals": [{"type": str(m.get("type") or ""), "name": str(m.get("name") or "")[:40], "time": str(m.get("time") or "")}
                      for m in _ensure_list(day.get("meals")) if isinstance(m, dict)],
            "legs_km": _legs(pts), "span_km": round(span, 1),
        })
        dno = out[-1]["day"]
        if dno in wins:
            out[-1]["window"] = "%02d:%02d-%02d:%02d" % (wins[dno][0] // 60, wins[dno][0] % 60, wins[dno][1] // 60, wins[dno][1] % 60)
        for key, label in (("transit_start", "day_start_transit"), ("transit_end", "day_end_transit")):
            brief = fin.transit_brief(day.get(key))
            if brief:
                out[-1][label] = brief
        if 1 <= dno <= len(wdays) and isinstance(wdays[dno - 1], dict) and wdays[dno - 1].get("sunset"):
            out[-1]["sunset"] = fin.clock_text(wdays[dno - 1]["sunset"])
    return out


def build_prompt(*, location: str, days: int, preferences: str, transport: str, origin: str, dates: str,
                 itinerary: List[Dict[str, Any]], known: List[str], round_no: int = 1, prior: Optional[List[str]] = None,
                 meta: Optional[Dict[str, Any]] = None, weather: Optional[Dict[str, Any]] = None) -> str:
    note = ""
    if round_no > 1:
        note = ("\n这是第 %d 轮复审：上一轮的问题已按意见做过调整（上一轮指出过：%s）。"
                "请只指出调整后仍然存在、或调整后新出现的问题；已经解决的不要再提，没有就返回空 issues。\n" % (round_no, "；".join((prior or [])[:6]) or "无"))
    return _TEMPLATE.format(round_note=note, pace_rule=_PACE_RULES[detect_pace(preferences)],
        location=location, days=days, preferences=preferences or "无特别偏好", transport=transport or "未指定",
        origin=origin or "未指定", dates=dates or "未指定",
        plan_json=json.dumps(build_plan_view(itinerary, meta, weather), ensure_ascii=False),
        known="；".join(known[:6]) if known else "无") + _FACTS


def normalize_review(obj: Dict[str, Any], days: int, model: str) -> Optional[Dict[str, Any]]:
    """清洗模型输出；结构不对返回 None。verdict 由代码按 high 问题判定，不信模型自报。"""
    if not isinstance(obj, dict) or ("issues" not in obj and "score" not in obj):
        return None
    issues: List[Dict[str, Any]] = []
    for it in _ensure_list(obj.get("issues")):
        if not isinstance(it, dict):
            continue
        try:
            day = int(it.get("day") or 0)
        except (TypeError, ValueError):
            continue
        sev = str(it.get("severity") or "").lower()
        typ = str(it.get("type") or "").lower()
        msg = voice.scrub_text(it.get("message")).strip()
        if not msg or day < 0 or day > days or sev not in SEVERITIES or typ not in ISSUE_TYPES:
            continue
        issues.append({"day": day, "severity": sev, "type": typ, "message": msg[:120], "fix": str(it.get("fix") or "").strip()[:160]})
        if len(issues) >= 8:
            break
    try:
        score = max(0, min(100, int(obj.get("score"))))
    except (TypeError, ValueError):
        score = max(0, 100 - 20 * sum(i["severity"] == "high" for i in issues) - 8 * sum(i["severity"] == "medium" for i in issues))
    return {"status": "ok", "model": model, "score": score, "summary": str(obj.get("summary") or "").strip()[:80],
            "verdict": "revise" if any(i["severity"] == "high" for i in issues) else "pass",
            "issues": issues, "revised_days": []}


def _names(day: Dict[str, Any]) -> List[str]:
    out = []
    for k in ("activities", "meals"):
        for x in _ensure_list(day.get(k)):
            if isinstance(x, dict) and str(x.get("name") or "").strip():
                out.append(str(x["name"]).strip())
    return out


def find_duplicates(itinerary: List[Dict[str, Any]]) -> Dict[int, List[str]]:
    """跨天重复的景点 / 餐厅（按名称，忽略大小写）：返回 {后出现的那一天: [名称]}。同一天内重复不算。"""
    seen: Dict[str, int] = {}
    out: Dict[int, List[str]] = {}
    for i, day in enumerate(sorted((d for d in itinerary if isinstance(d, dict)), key=lambda d: int(d.get("day") or 0))):
        dno = int(day.get("day") or i + 1)
        for n in dict.fromkeys(_names(day)):
            key = n.lower()
            if key in seen and seen[key] != dno:
                out.setdefault(dno, []).append(n)
            else:
                seen.setdefault(key, dno)
    return out


def used_elsewhere(itinerary: List[Dict[str, Any]], day: int) -> List[str]:
    """除某一天以外，其它天已经用到的地点名：重排这一天时要避开，避免再次出现跨天重复。"""
    names: List[str] = []
    for d in itinerary:
        if isinstance(d, dict) and int(d.get("day") or 0) != day:
            names += _names(d)
    return list(dict.fromkeys(names))


def actionable(review: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """需要处理的问题：high / medium，且类型可以靠重排解决（low 只是风格意见，不动）。"""
    if not review or review.get("status") != "ok":
        return []
    return [i for i in review.get("issues", []) if i["severity"] in ("high", "medium") and i["type"] in REVISABLE]


def plan_feedback(review: Optional[Dict[str, Any]], itinerary: List[Dict[str, Any]], max_n: int) -> Dict[int, Dict[str, Any]]:
    """把审核结果 + 代码发现的跨天重复，整理成 {day: {"feedback": 给编排器的修改要求, "avoid": 要避开的地点名, "issues": [..]}}。"""
    by_day: Dict[int, List[Dict[str, Any]]] = {}
    for i in actionable(review):
        if i["day"] > 0:
            by_day.setdefault(i["day"], []).append(i)
    for d, names in find_duplicates(itinerary).items():
        by_day.setdefault(d, []).append({"day": d, "severity": "medium", "type": "duplicate",
                                         "message": "与前面几天重复：" + "、".join(names[:4]),
                                         "fix": "换掉与前面几天重复的地点：" + "、".join(names[:4]) + "，选其它没用过的"})
    rank = sorted(by_day.items(), key=lambda kv: (-sum(x["severity"] == "high" for x in kv[1]), -len(kv[1]), kv[0]))[:max(0, max_n)]
    out: Dict[int, Dict[str, Any]] = {}
    for d, items in sorted(rank):
        fb = "；".join(dict.fromkeys((x.get("fix") or x["message"]) for x in items))[:420]
        out[d] = {"feedback": fb, "avoid": used_elsewhere(itinerary, d), "issues": items}
    return out


def select_revisions(review: Dict[str, Any], max_n: int) -> Dict[int, str]:
    """（兼容旧接口）只含 high 问题的天 → {day: 改法}。"""
    by_day: Dict[int, List[Dict[str, Any]]] = {}
    for i in review.get("issues", []):
        if i["day"] > 0 and i["severity"] == "high" and i["type"] in REVISABLE:
            by_day.setdefault(i["day"], []).append(i)
    ranked = sorted(by_day.items(), key=lambda kv: (-len(kv[1]), kv[0]))[:max(0, max_n)]
    return {d: "；".join((x["fix"] or x["message"]) for x in items)[:300] for d, items in sorted(ranked)}


def _day_label(msg: str, day: int) -> str:
    msg = re.sub(r"第\s*(\d+)\s*天", r"Day \1", msg)
    msg = re.sub(r"(?<=[\u4e00-\u9fff])(Day \d+)", r" \1", msg)  # 中文与 Day N 之间留空格
    msg = re.sub(r"(Day \d+)(?=[\u4e00-\u9fff])", r"\1 ", msg)
    return msg if (not day or msg.startswith("Day %d" % day)) else "Day %d：%s" % (day, msg)


def to_warnings(review: Optional[Dict[str, Any]]) -> List[str]:
    """闭环结束后，最终一版行程仍存在的硬伤（high）→ 用户可见的 warnings。
    其余（medium / low）是修订后的细节意见，只留在审核记录里，不打扰用户；季节 / 预算类另有去处。"""
    if not review or review.get("status") != "ok":
        return []
    return [_day_label(i["message"], i["day"]) for i in review.get("issues", [])
            if i["severity"] == "high" and i["type"] not in NOT_SHOWN]


def to_tips(review: Optional[Dict[str, Any]]) -> List[str]:
    """季节 / 节假日类的审核意见变成“出行提示”（日期未定时的泛泛之谈不要）。"""
    if not review or review.get("status") != "ok":
        return []
    out = []
    for i in review.get("issues", []):
        m = i["message"]
        if i["type"] == "season" and not re.search(r"未指定|无法判断|未提供|不确定", m):
            out.append("出行提示：" + _day_label(m, 0))
    return out[:2]


def public_view(review: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """随结果保存的精简版（不含给编排器的 fix）。"""
    if not review:
        return None
    if review.get("status") != "ok":
        out = {"status": review.get("status"), "model": review.get("model", "")}
        if review.get("fingerprint"):
            out["fingerprint"] = review["fingerprint"]
        if review.get('quality_gate'):out['quality_gate']=review['quality_gate']
        return out
    out = {"status": "ok", "model": review["model"], "score": review["score"], "summary": review["summary"],
           "verdict": review["verdict"],
           "issues": [{k: i[k] for k in ("day", "severity", "type", "message")} for i in review["issues"]]}
    if review.get("fingerprint"):
        out["fingerprint"] = review["fingerprint"]
    if review.get("source"):
        out["source"] = review["source"]
    if review.get('quality_gate'):out['quality_gate']=review['quality_gate']
    return out    # 轮次/初评分/调整的天数属于内部过程，不对用户展示


async def review_itinerary(*, router, model: str, location: str, days: int, preferences: str, transport: str,
                           origin: str, dates: str, itinerary: List[Dict[str, Any]], known: List[str],
                           round_no: int = 1, prior: Optional[List[str]] = None, weather: Optional[Dict[str, Any]] = None,
                           meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """调用审核模型。任何失败都返回 {status: skipped|failed}，不抛错。"""
    from ..services.long_review import policy
    cfg = policy(days, settings())
    prompt = build_prompt(location=location, days=days, preferences=preferences, transport=transport,
                          origin=origin, dates=dates, itinerary=itinerary, known=known, round_no=round_no, prior=prior,
                          meta=meta, weather=weather)
    from ..services.weather import planning_block
    prompt += '\n'+planning_block(weather)+'\n若不利天气下仍安排长时间户外/citywalk，列为 timing 或 theme 问题并给出可执行的室内/缩短步行修改意见。未知天气不得断言危险或晴朗。'
    if days >= 8:
        prompt += '\n长行程专项复核：逐一检查每次换城的抵达时刻、当晚与次晚住宿城市、行李与入住缓冲、跨城后剩余游览时间、首末日到机场/车站的真实缓冲、连续高强度步行与休息。住宿未定不等于已经预订；不可用上一城餐厅冒充下一城住宿。所有日期都要覆盖，不把高分当作通过条件。'
    try:
        res = await asyncio.wait_for(router.generate_json(
            location=location, days=days, preferences=preferences, system_prompt=_SYSTEM, user_prompt=prompt,
            temperature=0.0, step="critic", model=model), timeout=cfg["timeout_seconds"])
    except asyncio.TimeoutError:
        log.warning("critic 超时（%ss）→ 跳过审核", cfg["timeout_seconds"])
        return {"status": "skipped", "model": model}
    except Exception as e:                       # noqa: BLE001
        log.warning("critic 调用失败 → 跳过审核: %s", e)
        return {"status": "failed", "model": model}
    review = normalize_review(_extract_json_object(res.content), days, model)
    if review is None:
        log.warning("critic 输出无法解析 → 跳过审核")
        return {"status": "failed", "model": model}
    return review

