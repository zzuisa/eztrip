"""服务话术：eztrip 所有对用户可见的文字，统一成“专业旅行顾问”的口吻。

两层保障：
1. 提示词层——各个 prompt 注入同一套话术规范（PERSONA / GAPS / FORBIDDEN / 示例），
   让模型在“资料没覆盖的细节”上不再写“信息较少，建议查看官网”，而是给出带前提的安排或具体的下一步；
2. 出口层——scrub_*：模型偶尔仍会写出的套话（“目前查询到的资料里…信息较少”“建议自行查看官网”“以官方为准”
   “作为 AI…”）由代码按子句剔除，保留同一句里真正有用的部分。

注意：这里只管“措辞”。事实纪律不变——没有依据的票价、营业时间、班次一律不写，宁可不说也不编。
"""

from __future__ import annotations

import re
from typing import Any, Iterator, List, Optional

# ── 提示词片段 ────────────────────────────────────────────────────────────────

PERSONA = (
    "【服务口吻】您是一位专业、可靠的旅行顾问，沟通方式像高端酒店礼宾：称呼用“您”，语气沉稳、礼貌、有温度；"
    "先给明确结论与建议，再讲依据；表达肯定、具体、可执行，不堆砌客套、不过度道歉、不使用网络用语。"
)

GAPS = (
    "【资料没覆盖的细节怎么说】事实只来自已提供的资料与工具结果，绝不编造；但遇到没有覆盖的细节，"
    "不要说“资料较少 / 信息有限 / 暂未查到”，也不要把任务推回给用户（“建议您自行查看官网 / 以官方为准”）。请这样处理：\n"
    "① 先陈述已经确认的内容，直接给出结论；\n"
    "② 对未确认的细节，按同类场所的常规做法给出带前提的安排（如“已为这一站预留 2.5 小时，即使需要排队也不影响后面的安排”），不要把推测写成事实；\n"
    "③ 确实需要用户操作时，只写一个具体动作并说明原因（如“出发前一天在票务页锁定入场时段，周末更稳妥”），不写泛泛的“请查看官网”；\n"
    "④ 可以主动提出下一步服务（如“如您已确定日期，我可以据此继续微调当天的节奏”）。"
)

FORBIDDEN = (
    "【禁用表达】“目前查询到的资料里……信息较少 / 有限 / 不足”“暂未查询到”“建议您查看官网 / 自行核实”“请以官方为准”“仅供参考”"
    "“作为 AI / 语言模型”“我无法访问 / 读取”。不要提及自己是 AI 或模型。"
)

EXAMPLE = (
    "【示例】× “目前查询到的资料里，这家店的预订信息较少，建议查看官网。”\n"
    "✓ “这家店晚餐时段更受欢迎，建议把用餐安排在 18:30 前后入座；行程里已留出缓冲，即使需要等位也不会影响后面的安排。”"
)

# 对话类（地点问答、找点乐子、活动检索、出行顾问）
VOICE_CHAT = "\n".join([PERSONA, GAPS, FORBIDDEN, EXAMPLE])

# 行程文案类（景点描述、路线说明、提示、住宿理由、旅程旁白）：短句、不写“信息不足”
VOICE_COPY = (
    "【文案口吻】专业、克制、有信息量：每条说明写清“看什么 / 为什么值得 / 怎么玩更顺”，用肯定句；"
    "没有把握的细节直接不写，也不要写“信息较少 / 暂无资料 / 建议查看官网 / 以官方为准”；不使用“据说、可能、或许、大概”堆砌；不提及 AI 或模型。"
)

# 审核意见 / 提醒类：给用户看的一句话
VOICE_NOTICE = (
    "【提醒口吻】给用户看的话要像专业顾问的提示：先说结论或已做的处理，再说影响与建议，一句话说完；"
    "不用“信息较少 / 建议查看官网 / 以官方为准”这类推诿表达，不出现“AI”字样。"
)


def with_voice(system: str, block: str = VOICE_CHAT) -> str:
    """把话术规范拼到系统提示词后面（幂等）。"""
    return system if block in system else system.rstrip() + "\n\n" + block


# ── 出口净化 ──────────────────────────────────────────────────────────────────

_SRC = r"(?:资料|信息|数据|记录|搜索结果|检索结果|查询结果|评论|评价|攻略)"
_NOUN = r"(?:信息|资料|数据|内容|介绍|描述|记载|评价|评论|细节|详情)"
_LACK = r"(?:相对|比较|较为|较|偏)?(?:少|有限|不足|不多|不够|缺乏|缺少|不详|不明确|不充分|不完整|不全)"
_ACT = r"(?:前往|登录|访问|查看|查阅|参考|咨询|联系|关注|浏览|核实|核对|确认|去|上)"
_OFF = r"(?:官网|官方网站|官方渠道|官方页面|官方公告|官方信息|官方账号|官方公众号|官方网页|景区官网|官方售票|官方网站)"

PATTERNS = [
    # 目前查询到的资料里，XX 信息较少
    re.compile(_SRC + r"(?:里|中|显示|来看)?[，, ]?(?:[^，。！？；\n]{0,10}?" + _NOUN + r")?" + _LACK),
    # 目前查询到的资料里（只剩导语的子句）
    re.compile(r"^(?:(?:目前|现有|当前|已有|暂时)(?:查询到|检索到|搜索到|查到|收集到|掌握到?)?|(?:查询到|检索到|搜索到|查到|收集到|掌握到?))的?" + _SRC + r"(?:里|中|显示|来看)?$"),
    # 暂未查询到 / 未能找到 XX 信息
    re.compile(r"(?:暂未|尚未|未能|没能|没有|无法|不能|未)(?:查询|检索|搜索|查找|找|获取|查|核实)到?[^，。！？；\n]{0,14}?(?:" + _SRC + r"|详情|细节)"),
    # 建议您查看官网
    re.compile(r"(?:建议|推荐|请|可|可以|不妨|最好)(?:您)?(?:自行|另行)?" + _ACT + r"[^，。！？；\n]{0,10}?" + _OFF + r"(?![^，。！？；\n]{0,6}(?:预订|预约|购票|订票|下单|购买|抢票|报名))"),
    re.compile(r"(?:建议|请)(?:您)?(?:自行|另行)(?:核实|核对|确认|查询|了解)"),
    # 以官方为准
    re.compile(r"(?:请|务必|需|须|具体|最终|一切|均|仍)?以[^，。！？；\n]{0,12}?(?:官方|官网|现场|当日|实际|最新)[^，。！？；\n]{0,8}?为准"),
    # 仅供参考 / 身份声明
    re.compile(r"仅供参考|(?:作为|身为)[^，。！？；\n]{0,6}(?:AI|人工智能|语言模型|大模型)|我(?:只是|是)一个?(?:AI|人工智能|语言模型)|我(?:无法|不能|没办法)(?:访问|读取|浏览|联网|打开链接|获取实时)"),
]

_CLAUSE = re.compile(r"[^，,、]+[，,、]?")
_END = "。！？!?；;"
_MARK = re.compile(r"^(\s*(?:[-*•·]|\d{1,2}[.、)）])\s*)(.*)$", re.S)


def _hits(s: str) -> List[tuple]:
    out = []
    for p in PATTERNS:
        for m in p.finditer(s):
            out.append((m.start(), m.end()))
    return out


def _scrub_sentence(s: str) -> str:
    """s 含结尾标点。命中套话的子句剔除；同一句里有用的子句保留。"""
    core = s.rstrip(_END + " ")
    tail = s[len(core):]
    spans = _hits(core)
    pos, kept, any_bad, last_bad = 0, [], False, False
    for c in _CLAUSE.findall(core):
        a, b = pos, pos + len(c)
        pos = b
        bad = any(x < b and a < y for x, y in spans) or bool(PATTERNS[1].search(c.rstrip("，,、 ")))
        any_bad = any_bad or bad
        last_bad = bad
        if not bad:
            kept.append(c)
    if not any_bad:
        return s
    text = "".join(kept).rstrip("，,、 ")
    if not text:
        return ""
    return text + (tail if tail.strip() else ("。" if last_bad else ""))


def _scrub_line(line: str) -> str:
    """一行文字（可带列表标记与换行）。整行被剔光则返回 ""（连同换行）。"""
    nl = "\n" if line.endswith("\n") else ""
    body = line[:-1] if nl else line
    m = _MARK.match(body)
    mark, rest = (m.group(1), m.group(2)) if m else ("", body)
    out, buf = [], ""
    for ch in rest:
        buf += ch
        if ch in _END:
            out.append(_scrub_sentence(buf))
            buf = ""
    if buf:
        out.append(_scrub_sentence(buf) if _hits(buf) else buf)
    text = "".join(out)
    if not text.strip():
        return "" if (rest.strip() or mark.strip()) else line
    return mark + text + nl


def scrub_text(text: Any) -> str:
    """剔除套话，整理空行。输入非字符串原样转成字符串；全被剔光返回 ""。"""
    if text is None:
        return ""
    s = str(text)
    if not s:
        return ""
    out = "".join(_scrub_line(ln) for ln in s.splitlines(keepends=True))
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()


def has_hedge(text: Any) -> bool:
    s = str(text or "")
    return bool(_hits(s)) or bool(PATTERNS[1].search(s.strip()))


_SKIP_KEYS = {"name", "address", "place_id", "url", "time", "type", "id", "kind", "image", "images", "photo", "photos", "link", "website", "phone", "query", "search"}


def scrub_value(v: Any, key: str = "") -> Any:
    """递归净化结构里的文字字段；列表里被剔光的字符串项直接移除。"""
    if isinstance(v, str):
        return v if key in _SKIP_KEYS else scrub_text(v)
    if isinstance(v, list):
        out = []
        for x in v:
            y = scrub_value(x, key)
            if isinstance(x, str) and not str(y).strip():
                continue
            out.append(y)
        return out
    if isinstance(v, dict):
        return {k: scrub_value(x, str(k)) for k, x in v.items()}
    return v


class StreamScrubber:
    """流式输出的净化：按整行（或超长段落的整句）放行，避免把半句套话先发出去。"""

    FORCE = 140

    def __init__(self) -> None:
        self.buf = ""

    def feed(self, piece: str) -> str:
        self.buf += piece or ""
        out: List[str] = []
        while "\n" in self.buf:
            line, self.buf = self.buf.split("\n", 1)
            out.append(_scrub_line(line + "\n"))
        if len(self.buf) >= self.FORCE:
            cut = max(self.buf.rfind(c) for c in _END)
            if cut > 0:
                head, self.buf = self.buf[:cut + 1], self.buf[cut + 1:]
                out.append(_scrub_line(head))
        return "".join(out)

    def flush(self) -> str:
        rest, self.buf = self.buf, ""
        return _scrub_line(rest) if rest else ""


def scrub_stream(pieces: Iterator[str]) -> Iterator[str]:
    sc = StreamScrubber()
    for p in pieces:
        o = sc.feed(p)
        if o:
            yield o
    o = sc.flush()
    if o:
        yield o


def clean_or(text: Any, fallback: str = "") -> str:
    """净化；全被剔光时用 fallback。"""
    return scrub_text(text) or fallback

