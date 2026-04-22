# Research: Enforce File Line Limit

## Decision 1: 使用“仓库级脚本 + 统一输出格式”作为检查入口

- **Decision**: 采用单一仓库级命令作为检查入口，输出统一的通过/失败结果和违规明细。  
- **Rationale**: 统一入口可保证本地与 CI 一致，便于排查和推广。  
- **Alternatives considered**:
  - 仅依赖开发者本地编辑器提示（不一致、不可强制）
  - 在各子项目分别实现（重复维护成本高）

## Decision 2: 以“配置化扫描范围 + 例外清单”平衡治理与灵活性

- **Decision**: 规则支持受管控路径配置和受控例外列表，默认严格执行 500 行阈值。  
- **Rationale**: 可避免对文档、生成文件等误拦截，也允许少量业务必要例外并可审计。  
- **Alternatives considered**:
  - 全仓库无差别扫描（误报风险高）
  - 完全禁止例外（在特殊场景下阻塞交付）

## Decision 3: 失败报告必须“可直接修复”

- **Decision**: 失败输出至少包含文件路径、当前行数、阈值、超限差值，并按超限程度排序。  
- **Rationale**: 开发者首屏即可定位问题并制定拆分顺序，降低沟通成本。  
- **Alternatives considered**:
  - 仅输出失败计数（无法定位）
  - 输出过多原始信息（噪音高，不利于行动）

## Decision 4: 测试采用“样本文件 + 回归断言”模式

- **Decision**: 使用可控样本文件（499/500/501 行等）验证边界行为，并对输出文本进行断言。  
- **Rationale**: 行数规则的核心是边界正确性与输出稳定性，样本文件法最直接。  
- **Alternatives considered**:
  - 仅人工验证（不可回归）
  - 复杂 mock 文件系统方案（维护成本高）

## Decision 5: 与现有流程集成为“前置质量检查”

- **Decision**: 将该规则纳入标准开发与合并前检查路径。  
- **Rationale**: 只有进入标准流程才能保证“进入主分支前必检”。  
- **Alternatives considered**:
  - 仅文档约定（执行不稳定）
  - 仅 CI 检查（反馈过晚）

## Validation Appendix (T029)

- 行数规则全量检查：`PASS`（`checked=66 failed=0`）  
- US1 回归脚本：
  - `us1-block-overlimit.sh` -> `PASS`
  - `us1-pass-under-limit.sh` -> `PASS`
- US2 回归脚本：
  - `us2-multi-file-report.sh` -> `PASS`
  - `us2-rerun-after-fix.sh` -> `PASS`
- US3 回归脚本：
  - `us3-exception-valid.sh` -> `PASS`
  - `us3-exception-invalid.sh` -> `PASS`
- 前端单元测试：`npm run test` -> `5 files / 11 tests passed`
- 前端构建校验：`npm run build` -> `PASS`（仅保留大包体提示，无构建失败）
