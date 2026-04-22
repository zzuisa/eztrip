# 快速开始：智能行程优化与结果页升级

## 目标
在不重写现有体验的前提下，实现行程优化流程和结果页增强。

## 推荐实现顺序
1. 增加统一的行程规范化层。
2. 增加或扩展行程优化服务，并把后端结果映射为标准模型。
3. 抽离编辑状态持久化。
4. 抽离深链生成。
5. 抽离导出准备与文件生成。
6. 重构 `Result.vue`，改为组合这些服务和组合式函数。
7. 为完整流程补充单元测试与 E2E 测试。

## 可能变更的文件
- `frontend/src/services/api.ts`
- `frontend/src/views/Result.vue`
- `frontend/src/services/itinerary-normalizer.ts`（新建）
- `frontend/src/services/itinerary-optimizer.ts`（新建）
- `frontend/src/services/itinerary-persistence.ts`（新建）
- `frontend/src/services/deep-link-service.ts`（新建）
- `frontend/src/services/export-service.ts`（新建）
- `frontend/src/composables/useResultPage.ts`（新建）
- `frontend/src/composables/useMapState.ts`（新建）
- `frontend/src/composables/useItineraryEditing.ts`（新建）
- `frontend/src/types/itinerary.ts`（新建或扩展现有类型）

## 本地验证建议
- 确认结果页能够在多种行程负载结构下正常渲染。
- 确认编辑后刷新仍可恢复。
- 确认地图无法加载时能显示回退提示。
- 确认导出的 PNG/PDF 包含行程、预算和可用时的地图截图。
- 确认 Google Maps 深链保持地点顺序。

## 建议执行的检查
- 为规范化、链接生成和持久化工具运行单元测试。
- 为生成 → 查看 → 编辑 → 保存 → 刷新 → 导出流程运行 E2E 测试。
- 在移动端视口下手动检查长行程的可读性。
