"""德铁自然语言解析：确定性规则优先，信息不全时再问 LLM（带上柏林当前日期），LLM 失败时退回规则结果。

旧实现依赖 hello_agents.SimpleAgent + 已废弃的 get_llm().run()，迁移后恒抛异常，导致所有查询 500。
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

import httpx

from ...config import get_settings
from .debug import db_log

BERLIN = ZoneInfo("Europe/Berlin")


@dataclass
class DbPlan:
    origin: str = ""
    destination: str = ""
    time_mode: str = ""  # now | scheduled | ""(未说明 -> now)
    date: str = ""  # YYMMDD
    hour: str = ""  # HH
    minute: str = ""  # mm
    limit: int = 5
    regional_only: Optional[bool] = None  # None=用服务默认（月票口径 RE/RB/S）
    source: str = "rules"


def now_berlin() -> datetime:
    return datetime.now(BERLIN).replace(tzinfo=None)


# ---------------- 规则解析 ----------------

_WEEK = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6, "末": 5}
_FILLER = re.compile(
    r"(帮我|请帮我|麻烦|请问|请|查一下|查下|查查|查询|查|搜一下|搜|看一下|看下|看看|有哪些|有什么|有没有|有几趟|的车次|车次|班次|的车|火车|列车|的火车|的列车|"
    r"最近的?|最早的?|下一班|接下来|从|出发|出发地|目的地|trains?|connections?|from|please)",
    re.I,
)
_SEP = re.compile(r"\s*(?:到达?|至|去|往|→|->|=>|—>|—|-->|➜|➡️?)\s*|\s+(?:to|nach|->)\s+", re.I)


def _fmt(d: datetime) -> str:
    return d.strftime("%y%m%d")


def rule_parse(text: str, now: Optional[datetime] = None) -> DbPlan:
    now = now or now_berlin()
    s = (text or "").strip()
    plan = DbPlan()
    if not s:
        return plan

    # 长途/全部车种
    if re.search(r"ICE|\bIC\b|EC\b|长途|高铁|快车|全部车|所有车|含长途", s, re.I):
        plan.regional_only = False
    elif re.search(r"月票|区域车|RE\b|RB\b|S-?Bahn|市郊|D-?ticket|deutschlandticket", s, re.I):
        plan.regional_only = True

    s = re.sub(r"ICE|\bIC\b|\bEC\b|长途|高铁|快车|全部车|所有车|含长途|月票|区域车|\bRE\b|\bRB\b|S-?Bahn|市郊", " ", s, flags=re.I)

    # limit
    m = re.search(r"(\d{1,2})\s*(?:个|条|趟|班)", s)
    if m:
        plan.limit = max(1, min(int(m.group(1)), 20))
        s = s.replace(m.group(0), " ")

    # 日期
    date: Optional[datetime] = None
    m = re.search(r"(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})日?", s)
    if m:
        try:
            date = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            date = None
        s = s.replace(m.group(0), " ")
    if date is None:
        m = re.search(r"(\d{1,2})月(\d{1,2})[日号]?", s)
        if m:
            try:
                date = datetime(now.year, int(m.group(1)), int(m.group(2)))
                if date.date() < now.date() - timedelta(days=30):
                    date = date.replace(year=now.year + 1)
            except ValueError:
                date = None
            s = s.replace(m.group(0), " ")
    if date is None:
        for word, delta in (("大后天", 3), ("后天", 2), ("明天", 1), ("明早", 1), ("明晚", 1), ("今天", 0), ("今晚", 0), ("今早", 0), ("今日", 0)):
            if word in s:
                date = now + timedelta(days=delta)
                s = s.replace(word, " ", 1)
                # 明晚/今晚 -> 隐含傍晚
                if word.endswith("晚") and not re.search(r"\d\s*[点时:：h]", s):
                    plan.hour = plan.hour or "19"
                if word.endswith("早") and not re.search(r"\d\s*[点时:：h]", s):
                    plan.hour = plan.hour or "08"
                break
    if date is None:
        m = re.search(r"(下|这)?(?:周|星期|礼拜)([一二三四五六日天末])", s)
        if m:
            target = _WEEK[m.group(2)]
            if m.group(1) == "下":
                date = now - timedelta(days=now.weekday()) + timedelta(days=7 + target)
            else:
                date = now + timedelta(days=(target - now.weekday()) % 7)
            s = s.replace(m.group(0), " ")

    # 时间
    hour = minute = ""
    m = re.search(r"(?<!\d)(\d{1,2})\s*[:：]\s*(\d{2})(?!\d)", s)
    if m:
        hour, minute = m.group(1), m.group(2)
        s = s.replace(m.group(0), " ")
    else:
        m = re.search(r"(?<!\d)(\d{1,2})\s*(?:点|時|时|h|uhr)\s*(半|(\d{1,2})\s*分?)?", s, re.I)
        if m:
            hour = m.group(1)
            if m.group(2) == "半":
                minute = "30"
            elif m.group(3):
                minute = m.group(3)
            s = s.replace(m.group(0), " ")
    if hour:
        h = int(hour)
        if re.search(r"下午|晚上|傍晚|今晚|明晚", text) and h < 12:
            h += 12
        if re.search(r"凌晨|半夜", text) and h == 12:
            h = 0
        plan.hour = f"{min(max(h, 0), 23):02d}"
        plan.minute = f"{min(int(minute or 0), 59):02d}"
    if re.search(r"现在|当前|马上|立刻|立即|此刻|\bnow\b|\bjetzt\b|\bsofort\b|目前", text, re.I):
        plan.time_mode = "now"
        s = re.sub(r"现在|当前|马上|立刻|立即|此刻|\bnow\b|\bjetzt\b|\bsofort\b|目前", " ", s, flags=re.I)
    elif plan.hour or date:
        plan.time_mode = "scheduled"
        if date is None:
            date = now
        plan.date = _fmt(date)
        plan.hour = plan.hour or "08"
        plan.minute = plan.minute or "00"

    # 起终点
    s = re.sub(r"[，,。.!！?？]", " ", s)
    s = _FILLER.sub(" ", s)
    s = re.sub(r"(上午|下午|晚上|凌晨|傍晚|早上|中午|的)", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    parts = _SEP.split(s, maxsplit=1)
    if len(parts) == 2:
        origin = re.sub(r"^(?:von|ab|from)\s+", "", parts[0].strip(" -"), flags=re.I)
        plan.origin, plan.destination = origin.strip(" -"), parts[1].strip(" -")
    return plan


# ---------------- LLM 解析 ----------------

def _system_prompt(now: datetime) -> str:
    wd = "一二三四五六日"[now.weekday()]
    return (
        "你是德国铁路查询的参数抽取器。用户用中文/德文/英文描述想查的车次。\n"
        f"当前柏林时间：{now:%Y-%m-%d %H:%M}（星期{wd}）。把“明天/周五/下午3点”等相对时间换算成具体日期与小时。\n"
        "只输出一个 JSON 对象，不要任何多余文字：\n"
        '{"origin":"出发站","destination":"到达站","time":{"mode":"now|scheduled","date":"YYYY-MM-DD或null","hour":"HH或null","minute":"mm或null"},'
        '"limit":5,"regional_only":true|false|null}\n'
        "规则：1) origin/destination 用德国官方站名（中文城市转德文，如 杜塞尔多夫->Düsseldorf Hbf，慕尼黑->München Hbf，科隆->Köln Hbf）。"
        "2) 用户没说时间或说“现在/马上”时 mode=now。3) 用户明确提到 ICE/IC/长途/高铁/所有车时 regional_only=false；提到月票/区域车/RE/RB/S-Bahn 时 true；否则 null。"
        "4) limit 默认 5，用户指定数量时取该数（最大 20）。5) 缺起点或终点就把对应字段设为空字符串，不要猜。"
    )


def _model() -> str:
    s = get_settings()
    return os.getenv("EZTRIP_DB_NLQ_MODEL") or getattr(s, "llm_model_tool", "") or s.llm_model_content or s.llm_model_deepseek_v32


def llm_parse(text: str, now: Optional[datetime] = None, timeout: float = 20.0) -> Optional[Dict[str, Any]]:
    from ...services.llm_service import get_llm_router

    now = now or now_berlin()
    r = get_llm_router()
    if not r.api_key:
        return None
    payload = {
        "model": _model(),
        "messages": [
            {"role": "system", "content": _system_prompt(now)},
            {"role": "user", "content": text[:400]},
        ],
        "temperature": 0,
        "max_tokens": 300,
        **r._extra(),
    }
    resp = httpx.post(
        f"{r.base_url}/chat/completions",
        headers={"Authorization": f"Bearer {r.api_key}", "Content-Type": "application/json"},
        json=payload,
        timeout=timeout,
    )
    resp.raise_for_status()
    content = (((resp.json().get("choices") or [{}])[0]).get("message") or {}).get("content") or ""
    m = re.search(r"\{.*\}", content, flags=re.S)
    if not m:
        return None
    return json.loads(m.group(0))


def _merge_llm(plan: DbPlan, d: Dict[str, Any]) -> DbPlan:
    t = d.get("time") or {}
    out = replace(plan, source="llm")
    out.origin = out.origin or str(d.get("origin") or "").strip()
    out.destination = out.destination or str(d.get("destination") or "").strip()
    if not out.time_mode:
        mode = str(t.get("mode") or "").lower()
        if mode == "now":
            out.time_mode = "now"
        elif mode == "scheduled":
            ds = re.sub(r"\D", "", str(t.get("date") or ""))
            if len(ds) == 8:
                ds = ds[2:]
            hh = re.search(r"\d{1,2}", str(t.get("hour") or ""))
            mm = re.search(r"\d{1,2}", str(t.get("minute") or "0"))
            if len(ds) == 6 and hh:
                out.time_mode, out.date = "scheduled", ds
                out.hour = f"{min(int(hh.group(0)), 23):02d}"
                out.minute = f"{min(int(mm.group(0)) if mm else 0, 59):02d}"
    if out.regional_only is None and isinstance(d.get("regional_only"), bool):
        out.regional_only = d["regional_only"]
    try:
        lim = int(d.get("limit") or 0)
        if lim and out.limit == 5:
            out.limit = max(1, min(lim, 20))
    except Exception:
        pass
    return out


def parse_plan(text: str, now: Optional[datetime] = None, request_id: str = "nlq") -> DbPlan:
    now = now or now_berlin()
    plan = rule_parse(text, now)
    complete = bool(plan.origin and plan.destination)
    db_log(request_id, "nlq_rules", plan.__dict__)
    if not complete:
        try:
            d = llm_parse(text, now)
            db_log(request_id, "nlq_llm_raw", d)
            if d:
                plan = _merge_llm(plan, d)
        except Exception as e:  # noqa: BLE001  LLM 不可用时，规则结果仍可用
            print(f"[db-nlq] llm parse failed: {type(e).__name__}: {e}")
    if not plan.time_mode:
        plan.time_mode = "now"
    return plan

