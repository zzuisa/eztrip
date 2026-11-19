"""route_advisor（路线对比顾问）：把 MCP 算好的多方案对比，用两三句话讲清「选哪个、为什么、要注意什么」。

铁律：价格、时长、月票判定全部来自 MCP（代码），模型只做解释和取舍说明，不允许自己算账：
- 喂给模型的是已经算好的摘要；
- 输出里的每个金额都要能在数据里找到（route_compare.sanitize_advice），对不上就丢弃，改用规则文案（MCP 给的 headline）；
- 模型失败/超时/未配置 → 同样回退规则文案，对比结果本身不受影响。
"""

from __future__ import annotations

import asyncio
import os
from typing import Any, Awaitable, Callable, Dict, List, Optional

from ..agent_config import agent as agent_cfg
from ..services import route_compare as rc
from ..services import voice

SYSTEM = voice.with_voice(
    "你是 eztrip 的出行顾问，帮用户在几种去目的地的方式里做取舍。\n"
    "【事实纪律】下面的数据已经由程序算好（价格、时长、月票判定）。你只负责解释和取舍：金额必须原样引用数据里的数字，"
    "不得自己加减、换算或估一个新数字；没有的信息不要编。标记为「估算」的价格必须说明是估算。\n"
    "【写法】2～3 句，总共不超过 90 字：先说推荐哪一种以及最主要的原因（省钱或省时），再点出最关键的一个提醒"
    "（例如哪一段需要另付、价格只是估算、自驾与公共交通的差价、月票外的路段）。月票内的线路说「月票内」。"
    "推荐哪一种以数据里的「推荐方案」为准（可能是公共交通，也可能是自驾）：人数多时公交总价按人数相乘而自驾由全车共担，要把这一点讲清楚；"
    "如果程序给了「推荐理由」，以它为准，不要反驳。如果有 DB 方案，优先提醒区域快车（RE）更省钱。使用中文，不要用 Markdown，不要提及你是 AI 或模型；不要出现方案编号（如 t1、d1），用线路名或「自驾」指代方案。",
    voice.VOICE_NOTICE,
)


def _hm(m: Any) -> str:
    try:
        m = int(m)
    except (TypeError, ValueError):
        return "?"
    return f"{m // 60}h{m % 60:02d}" if m >= 60 else f"{m}分钟"


def digest(result: Dict[str, Any], leg: Optional[Dict[str, Any]] = None) -> str:
    """给模型看的紧凑摘要。"""
    lines: List[str] = []
    if leg:
        lines.append(f"路段：{(leg.get('from') or {}).get('name', '?')} → {(leg.get('to') or {}).get('name', '?')}")
    lines.append(f"月票：{'持有 Deutschlandticket' if result.get('ticket') == 'd_ticket' else '无'}；人数 {result.get('passengers', 1)}；推荐方案 {result.get('recommended')}")
    for o in result.get("options") or []:
        tags = "/".join(o.get("tags") or [])
        conf = {"live": "实时价", "estimate": "估算", "pass": "月票内"}.get(o.get("price_confidence"), "")
        if o.get("kind") == "drive":
            c = o.get("cost") or {}
            lines.append(f"[{o['id']}] 自驾 {_hm(o.get('duration_min'))} {o.get('distance_km')}km 约€{o['price']:.2f}（{conf}；能源€{c.get('energy_cost')} 过路费€{c.get('toll')}）")
            continue
        parts = []
        for l in o.get("legs") or []:
            if l.get("mode") != "TRANSIT":
                continue
            f = l.get("fare") or {}
            st = {"covered": "月票内", "pay": "另付", "unknown": "待核对"}.get(l.get("status"), "")
            price = f" €{f['amount']:.2f}" if f.get("amount") is not None and l.get("status") != "covered" else ""
            parts.append(f"{l.get('line')}({st}{price})")
        lines.append(f"[{o['id']}] {_hm(o.get('duration_min'))} 换乘{o.get('transfers')} 合计€{o['price']:.2f}（{conf}）{tags} {' + '.join(parts)}")
    if result.get("why"):
        lines.append("推荐理由（程序算好）：" + str(result["why"]))
    if result.get("notes"):
        lines.append("注意：" + "；".join(result["notes"]))
    return "\n".join(lines)


def fallback(result: Dict[str, Any]) -> str:
    h = str(result.get("why") or result.get("headline") or "").strip()
    return h or "已列出可选的出行方式，可按价格或时长选择。"


Completer = Callable[[List[Dict[str, str]]], Awaitable[str]]


async def advise(result: Dict[str, Any], leg: Optional[Dict[str, Any]] = None, complete: Optional[Completer] = None) -> Dict[str, str]:
    """返回 {text, source}；source=model 表示通过校验的模型文案，rule 表示规则文案。"""
    if complete is None or not (result.get("options") or []):
        return {"text": fallback(result), "source": "rule"}
    cfg = agent_cfg("route_advisor")
    timeout = float(cfg.get("timeout_seconds") or os.getenv("EZTRIP_ROUTE_ADVICE_TIMEOUT", "25"))
    msgs = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": digest(result, leg)}]
    try:
        raw = await asyncio.wait_for(complete(msgs), timeout)
    except Exception as e:  # noqa: BLE001
        print(f"[route_advisor] model failed {type(e).__name__}: {e}")
        return {"text": fallback(result), "source": "rule"}
    ok = voice.scrub_text(rc.sanitize_advice(raw, result) or "")
    if not ok:
        print("[route_advisor] advice rejected by validator")
        return {"text": fallback(result), "source": "rule"}
    return {"text": ok, "source": "model"}

