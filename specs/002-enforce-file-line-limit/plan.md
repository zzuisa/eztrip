# Implementation Plan: Enforce File Line Limit

**Branch**: `20260421-enforce-file-line-limit` | **Date**: 2026-04-22 | **Spec**: `/appHome/application/eztrip/specs/002-enforce-file-line-limit/spec.md`
**Input**: Feature specification from `/appHome/application/eztrip/specs/002-enforce-file-line-limit/spec.md`

## Summary

为仓库新增统一的“单文件不超过 500 行”治理能力，覆盖本地检查与团队一致执行。方案采用可配置的文件扫描规则、例外清单和清晰失败报告，确保开发者在合并前就能发现并修复超限文件，同时保留受控例外以支持必要场景。

## Technical Context

**Language/Version**: Bash（现有脚本体系）+ TypeScript（项目主开发语言）  
**Primary Dependencies**: 仓库现有 Shell 脚本体系、Node/NPM 脚本入口（不新增重型依赖）  
**Storage**: 文件系统配置（规则文件、例外清单）  
**Testing**: Vitest（前端测试基线）+ 脚本层回归验证（命令输出断言）  
**Target Platform**: Linux 开发环境与 CI 环境  
**Project Type**: Web application monorepo（`frontend/` + `backend/`）  
**Performance Goals**: 常规仓库规模下，单次全量扫描在 5 秒内完成  
**Constraints**: 单文件阈值固定为 500 行；结果必须稳定且可重复；失败提示必须可定位  
**Scale/Scope**: 作用于仓库受管控源码目录，不改动业务功能逻辑

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **VIII. 代码与架构必须可维护**：本特性直接服务可维护性目标，**PASS**  
- **X. 技术一致性与复用优先**：复用现有脚本与测试体系，不引入风格冲突，**PASS**  
- **I-VII（业务闭环/地图/导出等）**：本特性属于工程治理层，不改变旅游业务流程，**PASS（N/A to business behavior）**  
- **IX. 安全、隐私与范围控制**：仅处理源码行数元数据，不涉及用户隐私数据，**PASS**

结论：无违反宪法项，可进入设计与实施分解。

### Post-Design Re-check

- `research.md`、`data-model.md`、`contracts/`、`quickstart.md` 已产出且未引入与宪法冲突的设计。  
- 方案仍保持“可维护优先、技术一致性优先、不破坏业务闭环”的约束。  
- 二次门禁结论：**PASS**。

## Project Structure

### Documentation (this feature)

```text
specs/002-enforce-file-line-limit/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── line-limit-check-contract.md
└── tasks.md
```

### Source Code (repository root)

```text
.specify/
└── scripts/
   └── bash/
      └── (reuse existing script entry patterns)

frontend/
├── package.json
└── tests/
   └── unit/

backend/
└── (no business API schema change expected)
```

**Structure Decision**: 采用“文档驱动 + 轻量脚本落地”结构；实现主要落在仓库级脚本与配置文件，业务代码目录仅做最小接入（例如 npm script 或测试用例）。

## Complexity Tracking

本次规划无宪法豁免项，无需额外复杂度豁免记录。
