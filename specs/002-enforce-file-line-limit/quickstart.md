# Quickstart: Enforce File Line Limit

## 1. 前置条件

- 当前分支为 `20260421-enforce-file-line-limit`  
- 已存在 `spec.md`、`plan.md`、`research.md`、`data-model.md`、`contracts/`

## 2. 规划产物核对

- 确认规则目标：单文件最大 500 行  
- 确认例外策略：仅允许受控、可审计的例外条目  
- 确认失败输出：必须可直接定位和修复

## 3. 实现阶段建议顺序

1. 增加规则配置与例外清单文件  
2. 实现行数扫描与违规判定逻辑  
3. 实现统一输出与退出码约定  
4. 将检查接入本地开发与 CI 入口  
5. 补齐边界测试（499/500/501、多文件、例外、无效配置）

## 4. 验证清单

- 超过 500 行文件被稳定拦截  
- 500 行及以下文件稳定通过  
- 例外文件不误拦截，非例外文件不漏拦截  
- 输出包含路径、行数、阈值、超限差值  
- 本地与 CI 对同一提交给出一致结果

## 4.1 US1 快速验收

1. 运行 `bash .specify/scripts/bash/check-file-line-limit.sh --target "<relative-file>"`  
2. 当目标文件 >500 行时应失败并输出 `overflow` 字段  
3. 当目标文件 <=500 行时应通过并输出 `PASS`

## 5. 回归关注点

- 不影响现有业务功能与接口  
- 不引入明显性能退化  
- 不误伤文档、生成文件、第三方依赖目录

## 6. 例外维护规范

- 例外仅允许登记在 `.specify/line-limit/exceptions.json`  
- 每条例外必须包含 `filePath`、`reason`、`owner`  
- 推荐填写 `expiresAt`，到期后应自动失效并触发 warning  
- 路径无效或格式错误会告警且不会豁免超限判定

## 7. 端到端执行清单

1. `bash .specify/scripts/bash/check-file-line-limit.sh --mode all`  
2. `bash specs/002-enforce-file-line-limit/tests/us1-block-overlimit.sh`  
3. `bash specs/002-enforce-file-line-limit/tests/us1-pass-under-limit.sh`  
4. `bash specs/002-enforce-file-line-limit/tests/us2-multi-file-report.sh`  
5. `bash specs/002-enforce-file-line-limit/tests/us2-rerun-after-fix.sh`  
6. `bash specs/002-enforce-file-line-limit/tests/us3-exception-valid.sh`  
7. `bash specs/002-enforce-file-line-limit/tests/us3-exception-invalid.sh`
