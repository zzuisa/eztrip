# Tasks: Enforce File Line Limit

**Input**: Design documents from `/specs/002-enforce-file-line-limit/`  
**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/line-limit-check-contract.md`, `quickstart.md`

**Tests**: 本特性在 `spec.md` 中明确要求可验证与可回归，包含测试任务。  
**Organization**: 按用户故事分组，确保每个故事可独立实现和验证。

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行（不同文件、无直接依赖）
- **[Story]**: 对应用户故事（US1、US2、US3）
- 每条任务包含明确文件路径

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: 建立规则配置、脚本入口和最小运行框架

- [x] T001 新增规则配置文件 `/.specify/line-limit/rule.json`，定义默认 `maxLines=500` 与基础扫描范围
- [x] T002 新增例外配置文件 `/.specify/line-limit/exceptions.json`，定义条目结构（`filePath/reason/owner/expiresAt`）
- [x] T003 [P] 新增脚本入口 `/.specify/scripts/bash/check-file-line-limit.sh`，实现命令行参数解析与基础退出码骨架
- [x] T004 [P] 在 `/appHome/application/eztrip/frontend/package.json` 增加执行入口脚本（例如 `check:line-limit`）以便本地统一触发

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: 构建所有用户故事共享的扫描、判定与报告基础能力  
**⚠️ CRITICAL**: 未完成前不得进入任一用户故事实现

- [x] T005 在 `/.specify/scripts/bash/check-file-line-limit.sh` 实现受管控文件收集（含 include/exclude 规则）
- [x] T006 [P] 在 `/.specify/scripts/bash/check-file-line-limit.sh` 实现行数统计核心逻辑（支持 499/500/501 边界）
- [x] T007 [P] 在 `/.specify/scripts/bash/check-file-line-limit.sh` 实现结果结构化输出（`checkedFiles/failedFiles/results`）
- [x] T008 在 `/.specify/scripts/bash/check-file-line-limit.sh` 实现失败判定与退出语义（符合 contract 中 `exitCode` 约定）
- [x] T009 [P] 新增测试样本目录 `/specs/002-enforce-file-line-limit/test-fixtures/`，创建 `exact-500.txt`、`over-501.txt`、`under-499.txt`

**Checkpoint**: 行数检查基础设施就绪，可进入用户故事阶段

---

## Phase 3: User Story 1 - 防止超长文件进入主分支 (Priority: P1) 🎯 MVP

**Goal**: 在标准流程中稳定拦截超过 500 行的非例外文件  
**Independent Test**: 构造 520 行文件时检查失败，全部 <=500 时检查通过

### Tests for User Story 1

- [x] T010 [P] [US1] 新增脚本回归测试 `specs/002-enforce-file-line-limit/tests/us1-block-overlimit.sh`，验证超限触发失败
- [x] T011 [P] [US1] 新增脚本回归测试 `specs/002-enforce-file-line-limit/tests/us1-pass-under-limit.sh`，验证未超限通过

### Implementation for User Story 1

- [x] T012 [US1] 在 `/.specify/scripts/bash/check-file-line-limit.sh` 接入工作区文件扫描（支持针对待提交文件或全量文件）
- [x] T013 [US1] 在 `/.specify/scripts/bash/check-file-line-limit.sh` 增加违规明细输出（文件路径、行数、阈值、超限差值）
- [x] T014 [US1] 在 `/appHome/application/eztrip/start-dev.sh` 或等价开发入口加入行数检查调用（失败时中止）
- [x] T015 [US1] 在 `/appHome/application/eztrip/specs/002-enforce-file-line-limit/quickstart.md` 补充 US1 执行与验收步骤

**Checkpoint**: US1 独立可用，可在主流程前阻断超限文件

---

## Phase 4: User Story 2 - 快速定位与修复超限文件 (Priority: P2)

**Goal**: 输出可直接修复的报告，支持多文件场景  
**Independent Test**: 多个超限文件时可一次性列出并按超限程度排序

### Tests for User Story 2

- [x] T016 [P] [US2] 新增脚本回归测试 `specs/002-enforce-file-line-limit/tests/us2-multi-file-report.sh`，覆盖多文件违规输出
- [x] T017 [P] [US2] 新增脚本回归测试 `specs/002-enforce-file-line-limit/tests/us2-rerun-after-fix.sh`，覆盖修复后复检通过

### Implementation for User Story 2

- [x] T018 [US2] 在 `/.specify/scripts/bash/check-file-line-limit.sh` 增加违规结果排序与分组展示
- [x] T019 [US2] 在 `/.specify/scripts/bash/check-file-line-limit.sh` 增加“修复建议”提示（拆分、抽离模块、更新例外流程提示）
- [x] T020 [US2] 在 `/specs/002-enforce-file-line-limit/contracts/line-limit-check-contract.md` 更新示例输出以匹配实际字段与排序行为

**Checkpoint**: US2 完成后，开发者可快速定位并修复违规

---

## Phase 5: User Story 3 - 合理处理例外文件 (Priority: P3)

**Goal**: 实现受控例外机制，兼顾治理与灵活性  
**Independent Test**: 例外文件超限不失败，非例外超限仍失败；无效例外有警告

### Tests for User Story 3

- [x] T021 [P] [US3] 新增脚本回归测试 `specs/002-enforce-file-line-limit/tests/us3-exception-valid.sh`，验证有效例外行为
- [x] T022 [P] [US3] 新增脚本回归测试 `specs/002-enforce-file-line-limit/tests/us3-exception-invalid.sh`，验证无效路径警告与不豁免

### Implementation for User Story 3

- [x] T023 [US3] 在 `/.specify/scripts/bash/check-file-line-limit.sh` 实现例外清单加载与匹配逻辑
- [x] T024 [US3] 在 `/.specify/scripts/bash/check-file-line-limit.sh` 实现例外条目有效性校验（路径存在、到期检查）
- [x] T025 [US3] 在 `/.specify/scripts/bash/check-file-line-limit.sh` 为无效例外输出 warning，不影响其他文件判定
- [x] T026 [US3] 在 `/specs/002-enforce-file-line-limit/quickstart.md` 增加例外维护规范与回归步骤

**Checkpoint**: US3 完成后，规则具备受控豁免能力且可审计

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: 收尾验证、文档同步与质量加固

- [x] T027 [P] 统一清理与注释脚本 `/.specify/scripts/bash/check-file-line-limit.sh`，确保可维护性
- [x] T028 [P] 在 `/appHome/application/eztrip/specs/002-enforce-file-line-limit/quickstart.md` 增加完整端到端验证清单
- [x] T029 执行并记录全量验证（`frontend` 构建/测试 + 行数检查脚本回归），结果写入 `/appHome/application/eztrip/specs/002-enforce-file-line-limit/research.md` 附录
- [x] T030 对照 `spec.md` 的 FR-001~FR-008 与 SC-001~SC-004 做覆盖核对，补充到 `/appHome/application/eztrip/specs/002-enforce-file-line-limit/tasks.md` 末尾备注

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: 无依赖，可立即开始
- **Phase 2 (Foundational)**: 依赖 Phase 1，且阻塞所有用户故事
- **Phase 3 (US1)**: 依赖 Phase 2，MVP 首先完成
- **Phase 4 (US2)**: 依赖 US1 的基础输出结构
- **Phase 5 (US3)**: 依赖 US1/US2 的稳定判定和报告逻辑
- **Phase 6 (Polish)**: 依赖所有用户故事完成

### User Story Dependencies

- **US1 (P1)**: 可独立交付，提供核心拦截能力（MVP）
- **US2 (P2)**: 依赖 US1 结果数据结构，但可独立验证“可修复性”
- **US3 (P3)**: 依赖 US1 判定能力，独立验证例外机制

### Within Each User Story

- 测试任务先执行并应先出现失败（针对未实现行为）
- 实现任务完成后再次执行对应故事测试并通过

### Parallel Opportunities

- Setup 中 `T003`、`T004` 可并行
- Foundational 中 `T006`、`T007`、`T009` 可并行
- 各用户故事中的测试任务可并行（`T010/T011`、`T016/T017`、`T021/T022`）

---

## Parallel Example: User Story 1

```bash
# 并行执行 US1 测试准备
Task: "T010 [US1] 超限失败回归测试"
Task: "T011 [US1] 阈值内通过回归测试"

# 并行执行 US1 实现中的独立部分
Task: "T013 [US1] 违规明细输出"
Task: "T014 [US1] 开发入口接入"
```

---

## Implementation Strategy

### MVP First (US1 Only)

1. 完成 Phase 1 + Phase 2  
2. 完成 US1（Phase 3）  
3. 立即做独立验收：确认“>500 失败、<=500 通过”  
4. 满足后可作为首个可交付里程碑

### Incremental Delivery

1. US1：先把“拦截”做对  
2. US2：再把“报告与修复效率”做强  
3. US3：最后补“受控例外机制”

### Notes

- 全部任务均使用严格 checklist 格式  
- 每个任务均绑定了明确文件路径  
- 推荐每完成 1-3 个任务做一次小提交，保持回滚与审查清晰

## FR/SC Coverage Note (T030)

- FR-001/FR-002/FR-004/FR-007/FR-008：由 `check-file-line-limit.sh` 核心扫描、判定与流程接入实现。  
- FR-003：由违规明细输出（路径/行数/阈值/超限差值）实现。  
- FR-005/FR-006：由 `exceptions.json` 与例外有效性校验 + warning 输出实现。  
- SC-001/SC-004：通过统一脚本入口和固定排序输出保证一致执行。  
- SC-002：通过默认规则启用和主流程前置检查能力建立治理机制。  
- SC-003：通过 US2 的多文件报告与修复建议输出实现可定位可修复。
