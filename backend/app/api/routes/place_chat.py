"""地点详情页 AI 对话：上下文由后端根据 result_id + 地点标识可信组装，SSE 流式输出。"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any, AsyncIterator, Dict, List, Literal, Optional

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ...config import get_settings
from ...services import fun_chat as fc
from ...services import place_events as pe
from ...services import voice
from ...services.guest_guard import client_ip, get_quota, is_owner, limits as guest_limits
from ...services.chat_store import get_chat_store
from ...services.identity import set_cookie, user_key
from ...services.llm_service import get_llm_router
from ...services.model_config import get_model
from ...services.place_details_service import cache_key, get_place_details_service
from ...services.travel_plan_store import get_travel_plan_store

router = APIRouter(prefix="/travel-plan", tags=["PlaceChat"])

MAX_HISTORY = 6
MAX_MSG_CHARS = 800
MAX_OUTPUT_TOKENS = int(os.getenv("EZTRIP_CHAT_MAX_TOKENS", "700"))

SYSTEM_PROMPT = voice.with_voice(
    "你是 eztrip 的旅行向导，正在帮用户了解行程中的一个具体地点。"
    "只围绕「当前地点」和用户的这次行程回答；不编造开放时间、票价、预约规则或交通班次——没有依据的数字不写，"
    "改为结合这次行程给出稳妥的安排建议（到达时段、停留时长、缓冲时间、备选方案）。"
    "上下文里有评分、评论摘要、营业时间时要主动引用并点明来源（如“Google 评分 4.6，近期评论多提到……”）。"
    "回答要具体可执行、简洁：先给结论，再用 2-5 个要点展开，"
    "总长度控制在 300 字内（除非用户要求详细）。使用与用户相同的语言，可用简单 Markdown（加粗、列表）。"
)


class PlaceRef(BaseModel):
    day: int = Field(ge=1, le=60)
    kind: Literal["activity", "meal"] = "activity"
    name: str = Field(min_length=1, max_length=120)


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class PlaceChatRequest(BaseModel):
    result_id: str = Field(min_length=1, max_length=64)
    place: PlaceRef
    messages: List[ChatMessage] = Field(min_length=1, max_length=40)
    conversation_id: Optional[str] = Field(default=None, max_length=64)
    live: bool = False  # 前端明确要求查近期活动（快捷问题“近期活动”）


def _fmt(it: Dict[str, Any], keys: List[tuple]) -> List[str]:
    lines = []
    for label, key in keys:
        v = it.get(key)
        if v not in (None, "", 0, 0.0):
            lines.append(f"- {label}：{v}")
    return lines


def find_place(payload: Dict[str, Any], ref: PlaceRef) -> Optional[Dict[str, Any]]:
    """返回 {item, day, prev, next}；优先同天同名，其次全程同名。"""
    itin = [d for d in (payload.get("itinerary") or []) if isinstance(d, dict)]
    field = "meals" if ref.kind == "meal" else "activities"

    def scan(days: List[Dict[str, Any]]):
        for d in days:
            seq = []
            for a in d.get("activities") or []:
                seq.append(a)
            for m in d.get("meals") or []:
                seq.append(m)
            seq.sort(key=lambda x: str(x.get("time") or "99"))
            for it in d.get(field) or []:
                if isinstance(it, dict) and str(it.get("name")) == ref.name:
                    idx = next((i for i, x in enumerate(seq) if x is it), -1)
                    return {
                        "item": it, "day": d,
                        "prev": seq[idx - 1] if idx > 0 else None,
                        "next": seq[idx + 1] if 0 <= idx < len(seq) - 1 else None,
                    }
        return None

    return scan([d for d in itin if int(d.get("day") or 0) == ref.day]) or scan(itin)


def _review_lines(it: Dict[str, Any]) -> List[str]:
    """只读缓存（用户打开详情时已取过）：把 Google 评分/评论摘要喂给 AI，不产生新的计费请求。"""
    try:
        lat, lng = it.get("latitude"), it.get("longitude")
        key = cache_key(str(it.get("name") or ""), float(lat) if lat is not None else None, float(lng) if lng is not None else None)
        hit = get_place_details_service().peek(key)
    except Exception:  # noqa: BLE001
        return []
    d = (hit or {}).get("data")
    if not d:
        return []
    out = []
    if d.get("rating"):
        out.append("Google 评分：%s（%s 条评价）" % (d.get("rating"), d.get("rating_count") or "?"))
    if d.get("review_summary"):
        out.append("Google 评论摘要：" + str(d["review_summary"])[:300])
    for r in (d.get("reviews") or [])[:3]:
        if r.get("text"):
            out.append("近期评论（%s星，%s）：%s" % (r.get("rating"), r.get("relative") or "", str(r["text"])[:160]))
    op = d.get("opening") or {}
    wt, ti = op.get("weekday_text") or [], op.get("today_index")
    if wt and isinstance(ti, int) and 0 <= ti < len(wt):
        out.append("今日营业时间：" + wt[ti])
    return out


def build_context(payload: Dict[str, Any], found: Dict[str, Any], kind: str) -> str:
    it, day = found["item"], found["day"]
    parts = [
        f"目的地：{payload.get('location', '')}，共 {payload.get('days', '')} 天。",
        f"当前地点：{it.get('name')}（{'餐饮' if kind == 'meal' else '景点/活动'}），第 {day.get('day')} 天「{day.get('title', '')}」。",
    ]
    attrs = _fmt(it, [
        ("安排时间", "time"), ("地址", "address"), ("安排描述", "description"), ("路线说明", "route_desc"),
        ("预计花费", "estimated_cost"), ("门票", "ticket_price"), ("推荐理由", "preference_reason"),
    ])
    src = next((a for a in payload.get("attractions") or [] if isinstance(a, dict) and a.get("name") == it.get("name")), None)
    if src:
        attrs += _fmt(src, [("评分", "rating"), ("简介", "editorial_summary"), ("地址", "formatted_address")])
    parts += attrs
    for label, n in (("上一站", found.get("prev")), ("下一站", found.get("next"))):
        if n:
            parts.append(f"{label}：{n.get('name')}（{n.get('time', '')}）")
    parts += _review_lines(it)
    meta = payload.get("trip_meta") or {}
    if meta:
        parts.append("行程信息：" + "，".join(f"{k}={v}" for k, v in meta.items()))
    from ...services.weather import planning_block
    if payload.get('weather'):
        parts.append(planning_block(payload['weather'], int((found.get('day') or {}).get('day') or 1)))
    prefs = str(payload.get("request_preferences") or "").strip()
    if prefs:
        parts.append(f"用户生成行程时填写的偏好：{prefs[:200]}")
    return "\n".join(parts)[:3500]


def build_memory(uk: str, result_id: str, cid: Optional[str]) -> str:
    """跨地点记忆：用户在同一行程其它地点问过什么，让回答保持连贯（只含用户自己的提问，已截断）。"""
    try:
        items = get_chat_store().recent_user_questions(uk, result_id, cid, limit=6)
    except Exception:  # noqa: BLE001
        return ""
    if not items:
        return ""
    lines = [f"- 在「{i['place']}」问过：{i['q'][:80]}" for i in reversed(items)]
    return "【用户在本行程中的近期关注（供参考，不要逐条复述）】\n" + "\n".join(lines)


def chat_model() -> str:
    return get_model("place_chat")


def _sse(event: str, data: Dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def stream_chat(messages: List[Dict[str, str]]) -> AsyncIterator[str]:
    r = get_llm_router()
    if not r.api_key:
        raise RuntimeError("LLM 未配置")
    payload = {
        "model": chat_model(),
        "messages": messages,
        "temperature": 0.5,
        "stream": True,
        "max_tokens": MAX_OUTPUT_TOKENS,
        **r._extra(),
    }
    headers = {"Authorization": f"Bearer {r.api_key}", "Content-Type": "application/json"}
    timeout = httpx.Timeout(connect=8.0, read=60.0, write=10.0, pool=8.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream("POST", f"{r.base_url}/chat/completions", headers=headers, json=payload) as resp:
            if resp.status_code >= 400:
                await resp.aread()
                raise RuntimeError(f"upstream {resp.status_code}")
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except Exception:
                    continue
                delta = ((chunk.get("choices") or [{}])[0].get("delta") or {}).get("content") or ""
                if delta:
                    yield delta


@router.post("/place-chat", summary="地点详情 AI 对话（SSE 流式，带记忆）")
async def place_chat(req: PlaceChatRequest, request: Request):
    record = get_travel_plan_store().get(req.result_id)
    if not record:
        raise HTTPException(status_code=404, detail="记录不存在")
    payload = record.get("payload") or {}
    found = find_place(payload, req.place)
    if not found:
        raise HTTPException(status_code=404, detail="地点不存在于该行程")
    if req.messages[-1].role != "user":
        raise HTTPException(status_code=400, detail="最后一条消息必须来自用户")

    ip = client_ip(request)
    owner = is_owner(request)
    uk, new_uid = user_key(request)
    store = get_chat_store()
    question = req.messages[-1].content[:MAX_MSG_CHARS]

    conv = store.get(uk, req.conversation_id) if req.conversation_id else None
    if req.conversation_id and (not conv or conv["result_id"] != req.result_id):
        raise HTTPException(status_code=404, detail="对话不存在")
    if not owner:
        get_quota().consume("chat", ip, guest_limits()["chat"])

    if conv:
        cid = conv["id"]
        stored = store.messages(uk, cid, limit=MAX_HISTORY)
        history = [{"role": m["role"], "content": m["content"][:MAX_MSG_CHARS]} for m in stored]
    else:
        cid = store.create(uk, req.result_id, req.place.day, req.place.kind, req.place.name, str(payload.get("location") or ""))
        history = [{"role": m.role, "content": m.content[:MAX_MSG_CHARS]} for m in req.messages[:-1][-(MAX_HISTORY - 1):]]
    history.append({"role": "user", "content": question})
    history = history[-MAX_HISTORY:]
    if history and history[0]["role"] != "user":
        history = history[1:] or history

    system = SYSTEM_PROMPT + "\n\n【行程上下文（可信）】\n" + build_context(payload, found, req.place.kind)
    memory = build_memory(uk, req.result_id, cid)
    if memory:
        system += "\n\n" + memory

    # 近期活动：命中关键词（或前端明确要求）才走 MCP 工具循环；额度不足 / 服务不可用时退回普通问答并如实说明
    events = req.live or pe.wants_events(question)
    taken: List[tuple] = []
    site = ""
    if events:
        reason = ""
        if not pe.available():
            events, reason = False, "实时活动检索当前不可用"
        elif not owner:
            q, lim = get_quota(), guest_limits()
            try:
                q.consume("pevt", ip, lim["pevt"]); taken.append(("pevt", ip))
                q.consume("pevt_all", "all", lim["pevt_all"]); taken.append(("pevt_all", "all"))
            except HTTPException:
                for k, i in taken:
                    q.refund(k, i)
                taken, events, reason = [], False, "今日的实时活动检索额度已用完"
        site = pe.official_site(found["item"]) if events else ""
        system += pe.system_addendum(payload, req.place.day, req.place.name, events, reason, site, pe.urls_in(question))
    ev_model = get_model("fun_chat") if events else ""
    messages = [{"role": "system", "content": system}, *history]
    store.add_message(uk, cid, "user", question)

    async def gen() -> AsyncIterator[str]:
        got: List[str] = []
        sources: List[Dict[str, Any]] = []
        ev_cards: List[Dict[str, Any]] = []
        failed = False
        try:
            if events:
                yield _sse("meta", {"model": ev_model, "conversation_id": cid, "search": True})
                runner = pe.make_runner(found["item"], owner, ip, pe.make_context(payload, found, req.place.day))
                for u in [*pe.urls_in(question), *([site] if site else [])]:  # 用户贴的链接 / 官网可直接读取
                    runner.seen.add(fc._norm_url(u))
                for m in (conv and store.messages(uk, cid, limit=MAX_HISTORY)) or []:  # 续聊：此前搜索过的链接仍可核实
                    for src in ((m.get("extra") or {}).get("sources") or []):
                        if isinstance(src, dict) and src.get("url"):
                            runner.seen.add(fc._norm_url(src["url"]))
                text = ""
                async for kind, data in fc.run_turn(messages, runner, ev_model, specs=pe.EVENT_SPECS, max_tokens=800, max_rounds=pe.MAX_ROUNDS):
                    if kind == "status":
                        yield _sse("status", data)
                    elif kind == "sources":
                        sources.extend(data)
                        yield _sse("sources", {"items": data})
                    elif kind == "events":
                        ev_cards.extend(data)
                        yield _sse("events", {"items": data})
                    elif kind == "text":
                        text = data
                text = voice.scrub_text(text)
                if not text:
                    raise RuntimeError("empty answer")
                for i in range(0, len(text), 14):
                    got.append(text[i:i + 14])
                    yield _sse("delta", {"text": text[i:i + 14]})
                    await asyncio.sleep(0.012)
            else:
                yield _sse("meta", {"model": chat_model(), "conversation_id": cid})
                scrub = voice.StreamScrubber()
                async for piece in stream_chat(messages):
                    out = scrub.feed(piece)
                    if out:
                        got.append(out)
                        yield _sse("delta", {"text": out})
                tail = scrub.flush()
                if tail:
                    got.append(tail)
                    yield _sse("delta", {"text": tail})
            yield _sse("done", {"ok": True, "conversation_id": cid})
        except Exception as e:  # noqa: BLE001
            failed = True
            print(f"[place-chat] error {type(e).__name__}: {e}")
            if not got and not owner:
                get_quota().refund("chat", ip)
            if not got:
                for k, i in taken:
                    get_quota().refund(k, i)
            yield _sse("error", {"message": "暂时无法回答，请稍后重试"})
        finally:
            text = "".join(got).strip()
            if text:
                store.add_message(uk, cid, "assistant", text, ev_model or chat_model(), ({"sources": sources[:8], "events": ev_cards[:8]} if (sources or ev_cards) else None))
            elif failed:
                # 没有任何回答：撤销刚存的用户提问，避免历史里出现“问了没答”的孤儿
                store.drop_last_user(uk, cid)

    resp = StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )
    set_cookie(resp, request, new_uid)
    return resp
