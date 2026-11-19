"""旅程故事旁白：AI 为整趟行程写“有故事感”的逐站旁白，缓存进行程 payload，之后任何设备打开都直接可用。

- GET  /api/travel-plan/{id}/story  读取缓存（不耗额度）
- POST /api/travel-plan/{id}/story  生成（游客按 story 配额，站长不限；已存在且未 force 则直接返回）
旁白只做氛围与提示，不允许编造票价/开放时间等事实；失败时前端回退到本地生成的旁白，不影响播放。
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, HTTPException, Request

from ...config import get_settings
from ...services.guest_guard import client_ip, get_quota, is_owner, limits as guest_limits
from ...services.llm_service import get_llm_router
from ...services.model_config import get_model
from ...services import voice
from ...services.travel_plan_store import get_travel_plan_store

router = APIRouter(prefix="/travel-plan", tags=["TripStory"])

MAX_STOPS = 40
LINE_MAX = 90
TIP_MAX = 60
_gen_lock = asyncio.Lock()  # 同一进程内同时只生成一份，避免重复烧 token


def story_model() -> str:
    return get_model("story")


def _clip(v: Any, n: int) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()[:n]


def stop_key(day: int, name: str) -> str:
    return f"{day}|{name}"


def collect_stops(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """按天、按时间顺序列出行程中的景点/餐饮，供提示词与结果校验使用。"""
    out: List[Dict[str, Any]] = []
    for d in [x for x in (payload.get("itinerary") or []) if isinstance(x, dict)]:
        day = int(d.get("day") or 0) or (len(out) and out[-1]["day"]) or 1
        seq: List[Dict[str, Any]] = []
        for a in d.get("activities") or []:
            if isinstance(a, dict) and a.get("name"):
                seq.append({"kind": "景点", **a})
        seen = {s["name"] for s in seq}
        for m in d.get("meals") or []:
            if isinstance(m, dict) and m.get("name") and m["name"] not in seen:
                seq.append({"kind": "餐饮", **m})
        seq.sort(key=lambda x: str(x.get("time") or "99"))
        for it in seq:
            out.append({
                "day": day, "name": str(it["name"]), "kind": it["kind"], "time": _clip(it.get("time"), 20),
                "desc": _clip(it.get("description"), 100), "addr": _clip(it.get("address"), 60),
            })
    return out[:MAX_STOPS]


def build_prompt(payload: Dict[str, Any], stops: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    days = [x for x in (payload.get("itinerary") or []) if isinstance(x, dict)]
    lines = [f"目的地：{payload.get('location', '')}，共 {len(days) or payload.get('days', '')} 天。"]
    prefs = _clip(payload.get("request_preferences"), 200)
    if prefs:
        lines.append(f"旅行者偏好：{prefs}")
    for d in days:
        lines.append(f"\nDay {d.get('day')}「{_clip(d.get('title'), 30)}」{_clip(d.get('description'), 120)}")
        for s in (x for x in stops if x["day"] == int(d.get("day") or 0)):
            lines.append(f"  - [{s['kind']}] {s['name']} {s['time']} {s['desc']}".rstrip())
    system = (
        "你是旅行故事编剧，为一趟已经规划好的行程写“电影旁白式”的逐站文案，像杂志专栏或旅行 vlog 的画外音。"
        "要求：1) 使用中文（若行程主要是其他语言则用该语言）；2) 每站 line 为 1-2 句、不超过 70 字，写感受与画面（光线、声音、气味、节奏），"
        "承接上一站的情绪，不要罗列信息；3) tip 为一条不超过 40 字的实用小贴士，没有把握就留空字符串；"
        "4) 严禁编造具体票价、开放时间、预约规则、班次等事实，也不要虚构历史细节；5) 不使用 emoji；6) 文案专业、克制、有画面感，不写“信息较少 / 建议查看官网 / 以官方为准”，不提及 AI。"
        "只输出一个 JSON 对象，不要任何解释或代码块："
        '{"title":"整趟旅程的标题(≤14字)","subtitle":"一句话副标题(≤30字)",'
        '"days":[{"day":1,"headline":"当天主题(≤12字)","intro":"当天开场白(≤50字)"}],'
        '"stops":[{"day":1,"name":"与输入完全一致的地点名","line":"…","tip":"…"}],'
        '"outro":"整趟旅程的结尾感言(≤60字)"}'
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": "\n".join(lines)[:6000]}]


def parse_story(content: str, stops: List[Dict[str, Any]], payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """解析并净化 LLM 输出：只保留与真实行程匹配的站点；文本裁剪；不合格返回 None。"""
    m = re.search(r"\{.*\}", content or "", flags=re.S)
    if not m:
        return None
    try:
        raw = json.loads(m.group(0))
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(raw, dict):
        return None
    valid = {stop_key(s["day"], s["name"]) for s in stops}
    out_stops: Dict[str, Dict[str, str]] = {}
    for it in raw.get("stops") or []:
        if not isinstance(it, dict):
            continue
        try:
            day = int(it.get("day"))
        except (TypeError, ValueError):
            continue
        k = stop_key(day, _clip(it.get("name"), 120))
        line = _clip(voice.scrub_text(it.get("line")), LINE_MAX)
        if k in valid and line:
            out_stops[k] = {"line": line, "tip": _clip(voice.scrub_text(it.get("tip")), TIP_MAX)}
    if len(out_stops) < max(1, len(valid) // 2):
        return None  # 覆盖不足：视为失败，让前端用本地旁白
    out_days: Dict[str, Dict[str, str]] = {}
    for it in raw.get("days") or []:
        if isinstance(it, dict) and str(it.get("day", "")).isdigit():
            out_days[str(int(it["day"]))] = {"headline": _clip(it.get("headline"), 20), "intro": _clip(voice.scrub_text(it.get("intro")), 70)}
    return {
        "v": 1,
        "title": _clip(raw.get("title"), 24) or _clip(payload.get("location"), 24),
        "subtitle": _clip(raw.get("subtitle"), 40),
        "days": out_days,
        "stops": out_stops,
        "outro": _clip(voice.scrub_text(raw.get("outro")), 80),
    }


async def _complete(messages: List[Dict[str, str]]) -> str:
    r = get_llm_router()
    if not r.api_key:
        raise RuntimeError("LLM 未配置")
    payload = {
        "model": story_model(), "messages": messages, "temperature": 0.7,
        "max_tokens": int(os.getenv("EZTRIP_STORY_MAX_TOKENS", "3500")), **r._extra(),
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(connect=8.0, read=120.0, write=10.0, pool=8.0)) as c:
        resp = await c.post(
            f"{r.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {r.api_key}", "Content-Type": "application/json"},
            json=payload,
        )
    if resp.status_code >= 400:
        raise RuntimeError(f"upstream {resp.status_code}")
    return (((resp.json().get("choices") or [{}])[0]).get("message") or {}).get("content") or ""


def _record(result_id: str) -> Dict[str, Any]:
    rec = get_travel_plan_store().get(result_id)
    if not rec:
        raise HTTPException(status_code=404, detail="记录不存在")
    return rec


@router.get("/{result_id}/story", summary="读取已生成的旅程旁白")
async def get_story(result_id: str):
    rec = _record(result_id)
    pl = rec.get("payload") or {}
    return {"story": pl.get("story"), "stale": bool(pl.get("story_stale"))}


@router.post("/{result_id}/story", summary="生成旅程旁白（AI）")
async def make_story(result_id: str, request: Request, force: bool = False):
    rec = _record(result_id)
    payload = rec.get("payload") or {}
    force = force or bool(payload.get("story_stale"))  # 行程被编辑过，旧旁白已过期
    if payload.get("story") and not force:
        return {"story": payload["story"], "cached": True}
    stops = collect_stops(payload)
    if not stops:
        raise HTTPException(status_code=422, detail="行程里没有可写旁白的地点")

    ip = client_ip(request)
    owner = is_owner(request)
    if not owner:
        get_quota().consume("story", ip, guest_limits()["story"])
    try:
        async with _gen_lock:
            fresh = (get_travel_plan_store().get(result_id) or rec).get("payload") or {}
            if fresh.get("story") and not force and not fresh.get("story_stale"):  # 等锁期间别的请求已经生成
                if not owner:
                    get_quota().refund("story", ip)
                return {"story": fresh["story"], "cached": True}
            content = await _complete(build_prompt(payload, stops))
        story = parse_story(content, stops, payload)
        if not story:
            raise RuntimeError("旁白格式不合格")
        story["model"] = story_model()
        story["generated_at"] = int(time.time())
        get_travel_plan_store().update_payload(result_id, lambda p: (p.__setitem__("story", story), p.pop("story_stale", None)))
        return {"story": story, "cached": False}
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        if not owner:
            get_quota().refund("story", ip)
        print(f"[trip-story] error {type(e).__name__}: {e}")
        raise HTTPException(status_code=502, detail="旁白暂时无法生成，已使用默认旁白")

