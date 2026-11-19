"""规划上下文（每次请求一个）。

**为什么需要它**：子 Agent 之间要传递的是「候选池」这种大对象（几十个景点/餐饮）。
如果让 supervisor 用 tool-call 的 JSON 参数把它们来回搬运，token 会爆炸且极易出错。

做法（对齐 StockPilot：大数据留服务端、只把**摘要**回给 LLM）：
- 候选池存在本 `PlanningContext` 里，由子 Agent 读写；
- 子 Agent 的**工具入参只有小标量**（day / queries / theme）；
- 子 Agent **返回给 LLM 的只是摘要**（数量、名字列表），不是完整数据。

用 `ContextVar` 承载，天然隔离并发请求（每个 asyncio 任务各自一份）。
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


@dataclass
class PlanningContext:
    location: str
    days: int
    preferences: str = ""
    origin: str = ""
    emit: Optional[Callable] = None

    weather: Dict[str, Any] = field(default_factory=dict)
    experience: Dict[str, Any] = field(default_factory=dict)

    # 小红书灵感（可降级为空）
    insight: Dict[str, Any] = field(default_factory=dict)
    # 按天主题（strategy / supervisor 产出）
    day_themes: Dict[int, Dict[str, Any]] = field(default_factory=dict)
    # 候选池
    attractions_by_day: Dict[int, List[Dict[str, Any]]] = field(default_factory=dict)
    meals_by_day: Dict[int, List[Dict[str, Any]]] = field(default_factory=dict)
    meal_sources: Dict[int, Dict[str, Any]] = field(default_factory=dict)
    # 候选不足 / 模型输出无效而走了保守兜底的天（用于生成真实 warnings）
    fallback_days: set = field(default_factory=set)
    # 行程元信息（仅供审核参考）
    start_date: str = ""
    transportation: str = ""
    # 预选住宿（可空）：每天从住宿出发并回到住宿
    stay_name: str = ""
    # composer 按天分配的景点（审核后重排用）与审核意见
    assigned: Dict[int, List[Dict[str, Any]]] = field(default_factory=dict)
    review_feedback: Dict[int, str] = field(default_factory=dict)
    # 带审核意见重排时使用的模型（空 = 沿用编排模型）：按意见改写需要更强的指令遵从
    revise_model: str = ""
    # 营业时间校验（agents/feasibility.py）每次润色后重算：解决不了、需要提醒用户的问题
    hours_issues: List[str] = field(default_factory=list)
    # 行程元信息（出发地/租车/每日可游览窗口/返程点…）：settle（最终化）用它排定到达/取还车/返程。
    # None = 不做最终化（多城市串联的中间站，由合并后的整体统一最终化）
    trip_meta: Optional[Dict[str, Any]] = None

    def all_attractions(self) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for day in sorted(self.attractions_by_day):
            out.extend(self.attractions_by_day[day])
        return out

    def all_meals(self) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for day in sorted(self.meals_by_day):
            out.extend(self.meals_by_day[day])
        return out


_ctx: ContextVar[Optional[PlanningContext]] = ContextVar("planning_context", default=None)


def set_context(ctx: PlanningContext) -> None:
    _ctx.set(ctx)


def get_context() -> PlanningContext:
    ctx = _ctx.get()
    if ctx is None:
        raise RuntimeError("PlanningContext 未设置（子 Agent 只能在规划请求内调用）")
    return ctx


async def emit(ev: Dict[str, Any]) -> None:
    """向 SSE 推事件（无 emit 时静默丢弃）。"""
    ctx = _ctx.get()
    if not ctx or not ctx.emit:
        return
    try:
        await ctx.emit(ev)
    except Exception:
        pass
