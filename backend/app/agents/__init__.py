"""多 Agent 运行时：supervisor（动态委派）+ 领域子 Agent（对齐 StockPilot）。

- `supervisor`：`agents.supervisor.run_supervisor(...)` —— tool-calling 循环，把能力总线交给它，
  自主决定委派哪个子 Agent；产出**策展后的候选池**，不产出行程 JSON。
- `composer`：把候选池按天**并发**编成严格 `TravelPlanData` JSON。
- 子 Agent：作为**总线工具**存在（见 `subagents.py`）。导入本包即完成注册。
"""

from . import subagents as subagents  # noqa: F401  —— import 即把子 Agent 注册进 tools.REGISTRY

__all__ = ["subagents"]
