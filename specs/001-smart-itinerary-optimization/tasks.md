# 任务清单：智能行程优化与结果页全面升级

**输入**：`/specs/001-smart-itinerary-optimization/` 下的 `spec.md`、`plan.md`、`research.md`、`data-model.md`、`contracts/`
**前置条件**：已完成需求规格、实现计划与数据模型设计

**目标**：基于现有 `Result.vue` 与 `frontend/src/services/api.ts` 的能力，完成“智能行程优化 + 结果页全面升级”的可执行任务拆分，支持后续 `/speckit-implement` 逐步落地。

**说明**：
- `[P]` 表示可并行执行（不同文件、无依赖冲突）
- `US1/US2/...` 表示对应用户故事
- 第一阶段必须完成核心闭环：数据规范化 + 结果页稳定展示 + 编辑保存 + 地图联动 + 导出
- 第二阶段再做增强项：故事化浏览、更多边缘案例处理、性能优化等

---

## Phase 0：紧急修复 —— 景点查询超过 3 天游走超时问题

**目标**：先解决当前最严重的可用性问题——用户查询某旅行景点/行程天数超过 3 天时容易触发超时或请求失败，优先保证“能生成、能返回、能看见”。

**独立验收**：当用户输入 4 天及以上行程时，请求不再因默认超时而失败；若生成仍需较长时间，页面能显示进度/降级结果，并最终返回可用行程。

- [x] T000 [P] 修改 `frontend/src/services/api.ts` 中旅行计划相关请求的超时与请求策略，针对 4 天游程及更长行程提升超时上限，并优先使用更稳妥的流式/分段返回路径。**验收标准**：4 天及以上请求不再默认超时；请求失败时有明确错误；不影响 3 天游程及以下的正常调用。
- [x] T001 [P] 在 `frontend/src/services/api.ts` 中为长行程请求增加进度回调/兜底降级处理，确保服务端处理中用户能看到“生成中”的状态而不是直接失败。**验收标准**：请求等待期间有可见状态；中间失败可重试或降级；页面不会卡死。
- [x] T002 [P] 在 `frontend/src/views/Result.vue` 或行程生成入口页面增加长行程请求的错误提示与重试入口，避免用户因超时失去当前输入。**验收标准**：长行程失败时用户可以重试；输入内容不丢失；提示信息清晰可理解。
- [x] T003 [P] 补充长行程超时回归测试 `frontend/tests/unit/api-timeout.spec.ts`（或等价目录），覆盖 3 天游程成功、4 天游程不超时、失败兜底三类场景。**验收标准**：测试能复现并验证超时策略；长行程场景有回归保护。

**依赖关系**：T001 依赖现有 `api.ts`；T002 依赖 T001；T003 依赖 T001、T002。

---

## Phase 1：基础设施与核心数据层

**目标**：建立统一数据模型、规范化层与持久化基础，为结果页和智能行程优化提供稳定输入。

- [x] T004 [P] 新建统一类型定义文件 `frontend/src/types/itinerary.ts`，补充 `TripRequest`、`OptimizedItinerary`、`TripDay`、`PlaceItem`、`BudgetSummary`、`NavigationLink`、`ResultViewState` 等核心类型。**验收标准**：类型可被 `api.ts`、`Result.vue` 与后续服务复用，且通过 TypeScript 严格类型检查。
- [x] T005 [P] 新建行程数据规范化服务 `frontend/src/services/itinerary-normalizer.ts`，将现有 `TripPlanResponse`、`TravelPlanResponseV2` 及 sessionStorage 中的多种结构统一转换为标准运行时模型。**验收标准**：至少支持 5 类输入结构；缺失字段可降级展示；标准输出可直接供结果页使用。
- [x] T006 [P] 新建行程持久化服务 `frontend/src/services/itinerary-persistence.ts`，负责保存/恢复用户编辑后的标准化行程数据。**验收标准**：同一行程刷新后可恢复；保存失败有明确错误返回；不依赖视图组件内部状态。
- [x] T007 [P] 新建行程辅助工具 `frontend/src/utils/itinerary-helpers.ts`，沉淀格式化、分组、时长计算、预算汇总等通用方法。**验收标准**：结果页重复逻辑可逐步迁移到该工具；工具函数可独立测试。
- [x] T008 新建 `frontend/src/services/itinerary-optimizer.ts`，封装“智能行程优化”请求/适配逻辑，统一接收旅行天数、预算、偏好与约束，并产出标准化行程结果。**验收标准**：输入输出结构明确；生成结果可映射到标准行程模型；预算与时长约束可被验证。

**依赖关系**：T005 依赖 T004；T006 依赖 T004、T005；T007 依赖 T004；T008 依赖 T004、T005。

---

## Phase 2：结果页核心闭环（MVP）

**目标**：优先完成“查看 → 调整 → 导航 → 导出 → 分享”的最小可用闭环，并确保结果页稳定渲染。

### User Story 2 - 查看与调整结果（Priority: P1）

**目标**：结果页能够稳定展示标准化行程，并支持编辑、保存与刷新恢复。

**独立验收**：打开任意标准化行程后，页面可正常渲染；修改顺序/删除条目后可保存；刷新后可恢复。

- [x] T009 [P] 新建结果页组合式函数 `frontend/src/composables/useItineraryEditing.ts`，管理编辑模式、行程副本、拖拽排序、删除、插入与保存状态。**验收标准**：编辑逻辑从 `Result.vue` 中抽离；修改后状态可回写到持久化层；支持独立单测。
- [x] T010 [P] 新建结果页组合式函数 `frontend/src/composables/useResultPage.ts`，统一管理 `activeSection`、`activeDays`、`selectedPlaceKey`、`deepLinkVisible`、`exportStatus` 等页面状态。**验收标准**：页面状态集中管理；可被 `Result.vue` 直接消费；不包含复杂业务逻辑。
- [ ] T011 [P] 新建地图状态组合式函数 `frontend/src/composables/useMapState.ts`，管理标记、路线图层、当前选中地点、故事面板状态和地图失败 fallback。**验收标准**：地图联动逻辑从视图中抽离；支持按天切换；地图失败时可切换为文本优先展示。
- [ ] T012 重构 `frontend/src/views/Result.vue`，接入 `useItineraryEditing`、`useResultPage`、`useMapState` 和 `itinerary-normalizer`，并优先复用现有页面结构与样式。**验收标准**：页面仍保留现有概览/预算/地图/日程/天气结构；结果页在不同数据结构下稳定显示；编辑状态、选中态与展开态不丢失。
- [ ] T013 修改 `frontend/src/services/api.ts`，将旅行计划生成结果统一映射到标准化模型，并补充生成/流式生成接口的适配路径。**验收标准**：现有接口调用方式不被破坏；新旧结构都能被规范化处理；生成结果可直接进入结果页展示。

**依赖关系**：T009 依赖 T006；T010 依赖 T004、T005；T011 依赖 T004、T005；T012 依赖 T005、T009、T010、T011；T013 依赖 T004、T005。

---

### User Story 3 - 使用深链导航（Priority: P2）

**目标**：从当前天或当前选中条目生成 Google Maps 多点导航深链。

**独立验收**：点击导航按钮可正确打开顺序一致的地图路线；缺失坐标时自动跳过不可导航项。

- [ ] T014 [P] 新建深链服务 `frontend/src/services/deep-link-service.ts`，根据标准化地点序列生成 Google Maps 单点/多点/当天路线链接。**验收标准**：支持按顺序生成多点导航；可在缺少坐标时自动降级；输出结果可独立测试。
- [ ] T015 将 `frontend/src/views/Result.vue` 中当前的导航按钮逻辑替换为调用 `deep-link-service`，并与当前选中项、当前天索引保持联动。**验收标准**：从“当天行程”和“当前选中地点”两种入口都能生成正确深链；按钮行为与页面状态一致。
- [ ] T016 [P] 补充深链相关测试 `frontend/tests/unit/deep-link-service.spec.ts` 或等价目录，覆盖顺序、缺坐标降级与空列表场景。**验收标准**：测试覆盖至少 3 类输入；链接顺序与预期一致；无坐标项不进入路线。

**依赖关系**：T014 依赖 T004、T005；T015 依赖 T010、T014；T016 依赖 T014。

---

### User Story 4 - 导出并分享行程（Priority: P2）

**目标**：支持将完整结果导出为图片与 PDF，且包含地图截图、预算明细与日程信息。

**独立验收**：同一行程可以分别导出 PNG 和 PDF；导出文件中包含完整核心信息；地图不可用时仍能成功导出。

- [ ] T017 [P] 新建导出服务 `frontend/src/services/export-service.ts`，抽离图片/PDF 的准备、快照、下载与错误回退逻辑。**验收标准**：导出服务不依赖 `Result.vue` 内部临时变量；支持地图可用/不可用两种路径；导出过程可独立测试。
- [ ] T018 [P] 将 `frontend/src/views/Result.vue` 中的图片导出与 PDF 导出逻辑替换为调用 `export-service`，并保留现有导出入口与交互文案。**验收标准**：页面导出按钮行为不变；导出内容仍包含地图、预算和日程；失败时提示友好。
- [ ] T019 [P] 为导出服务补充测试 `frontend/tests/unit/export-service.spec.ts` 或等价目录，覆盖地图快照成功/失败、PNG/PDF 输出和大内容场景。**验收标准**：至少覆盖成功与降级两条路径；输出格式正确；异常可被捕获。

**依赖关系**：T017 依赖 T004、T005；T018 依赖 T017、T012；T019 依赖 T017。

---

## Phase 3：智能行程优化与预算约束

**目标**：完成“智能行程优化”输入、生成与约束校验，确保在预算与时长要求下生成可执行方案。

### User Story 1 - 生成优化行程（Priority: P1）

**目标**：输入旅行天数、预算范围与偏好后，生成一份高性价比、可执行的按日行程。

**独立验收**：提交不同预算与偏好组合时，能生成标准化行程；总花费不明显超出预算；每日安排合理。

- [ ] T020 [P] 新建或扩展行程输入/输出契约文件 `frontend/src/types/itinerary.ts` 与必要的接口定义，补充生成请求与返回结构。**验收标准**：生成输入、优化结果与结果页数据模型保持一致；可被测试直接引用。
- [ ] T021 [P] 在 `frontend/src/services/itinerary-optimizer.ts` 中实现预算、偏好、天气与饮食限制的优化规则与兜底策略。**验收标准**：低预算时优先免费/低成本项目；雨天优先室内方案；饮食限制能过滤不合适项；规则可被单测覆盖。
- [ ] T022 修改 `frontend/src/services/api.ts` 的行程生成调用路径，使其支持智能行程优化输入，并将返回结果统一交给规范化层。**验收标准**：现有生成入口继续可用；新输入可被接收；返回结果可直接进入结果页。
- [ ] T023 [P] 为智能行程优化补充单元测试 `frontend/tests/unit/itinerary-optimizer.spec.ts`，覆盖预算上限、时长限制、偏好命中和边缘约束场景。**验收标准**：至少覆盖 4 类约束；测试可重复且稳定；生成结果可验证。

**依赖关系**：T020 依赖 T004；T021 依赖 T020；T022 依赖 T020、T005、T021；T023 依赖 T021。

---

## Phase 4：地图联动、故事化浏览与交互增强

**目标**：在核心闭环稳定后，增强地图体验、故事化浏览和多设备交互表现。

- [ ] T024 [P] 完善 `frontend/src/composables/useMapState.ts`，把路线绘制、地点聚焦、故事面板切换、当前天动画等逻辑完全封装。**验收标准**：地图相关逻辑不再散落在 `Result.vue`；切换日期时地图状态同步更新；单测可覆盖主要状态变化。
- [ ] T025 [P] 在 `frontend/src/views/Result.vue` 中保留并整理故事化浏览与行程高亮展示，但改为依赖 `useMapState` 的统一状态输出。**验收标准**：当前日故事卡片、下一个地点预告、路线图例仍可显示；地图与列表联动高亮正常。
- [ ] T026 [P] 优化 `frontend/src/views/Result.vue` 的移动端布局与交互区块，确保主要按钮、卡片和地图区域在小屏上更易触达。**验收标准**：移动端横向溢出减少；关键按钮可见；长行程下仍可滚动阅读。
- [ ] T027 [P] 补充移动端与桌面端 E2E 测试场景 `frontend/tests/e2e/result-page.spec.ts`，覆盖查看、切换、导航、导出与编辑主链路。**验收标准**：至少覆盖一条完整移动端链路与一条桌面端链路；页面可稳定通过测试。

**依赖关系**：T024 依赖 T011；T025 依赖 T024、T012；T026 依赖 T012；T027 依赖 T012、T015、T018、T026。

---

## Phase 5：边缘案例、降级与质量收尾

**目标**：补齐缺失字段、离线/失败、性能与文档等跨切面能力。

- [ ] T028 [P] 为 `frontend/src/services/itinerary-normalizer.ts` 增加更多边缘结构适配规则，覆盖字段缺失、嵌套活动、弱结构 meals/activities 等场景。**验收标准**：结果页在至少 5 类数据结构下稳定渲染；缺失字段不会导致空白页或崩溃。
- [ ] T029 [P] 为 `frontend/src/views/Result.vue` 和 `useMapState.ts` 增加地图失败、图片加载失败、无坐标地点等 fallback 展示。**验收标准**：地图失败时页面继续可用；导出/导航在缺失坐标场景有明确提示；不出现静默失败。
- [ ] T030 [P] 增加离线或缓存计划查看的支持逻辑，优先恢复已缓存行程并避免阻塞页面加载。**验收标准**：网络受限时仍能看到最近一次保存的行程；页面不会因为请求失败而完全不可用。
- [ ] T031 [P] 统一补充结果页相关单元测试与回归测试 `frontend/tests/unit/`、`frontend/tests/integration/`，覆盖规范化、编辑保存、地图联动、导出和深链。**验收标准**：核心流程具备稳定测试覆盖；回归用例能捕获关键兼容问题。
- [ ] T032 [P] 更新 `specs/001-smart-itinerary-optimization/quickstart.md` 与必要的项目说明文档，写明本次功能的运行、验证和回归路径。**验收标准**：文档能指导开发者按步骤完成本功能；与现有实现保持一致。
- [ ] T073 [P] 新增预算约束自动化测试 `frontend/tests/unit/itinerary-budget-guard.spec.ts`，显式断言“生成总花费 <= 用户预算上限的 110%（SC-002）”。**验收标准**：覆盖正常、低预算、异常输入三类用例；断言失败可定位到超额原因。
- [ ] T074 [P] 新增日程时长守卫与测试 `frontend/src/utils/itinerary-duration-guard.ts`、`frontend/tests/unit/itinerary-duration-guard.spec.ts`，显式断言“每日活动总时长 <= 12 小时（SC-003）”。**验收标准**：超限时触发回退或裁剪策略；测试覆盖多天与缺失时长场景。
- [ ] T075 [P] 新增结果页性能基线测试与采样脚本 `frontend/tests/integration/result-performance.spec.ts`（或等价路径），量化“首屏可交互、地图初始化、列表交互”阈值（SC-007）。**验收标准**：至少定义并验证 3 个性能阈值；阈值写入测试注释与 quickstart。
- [ ] T076 [P] 新增需求-任务映射校验文档 `specs/001-smart-itinerary-optimization/coverage-matrix.md`，建立 FR/SC 与任务 ID 的一一映射。**验收标准**：FR-001~FR-018、SC-001~SC-008 均可追溯；新增需求时可快速补任务。

**依赖关系**：T028 依赖 T005；T029 依赖 T011、T017；T030 依赖 T006、T012；T031 依赖 T012、T015、T022；T032 依赖核心实现完成；T073 依赖 T021、T022；T074 依赖 T007、T012；T075 依赖 T012、T024、T026；T076 依赖 T032。

---

## Phase 6：用户故事 6 - 生成入口全屏 Loading 现代化过渡（Priority: P1）

**目标**：用户点击“生成旅途”后，首页通过 500-600ms 的平滑动画过渡进入全屏 Loading（半透明遮罩 + backdrop blur + 呼吸光效背景 + 进度环 + 执行状态 + 用户友好日志），并支持中途取消与优雅回退；完成后以 out-in 平滑过渡到结果页。

**独立验收**：
- 移动端低端机（节流/模拟）下动画仍流畅（以 transform/opacity 为主，避免布局抖动）
- Loading UI 不展示任何 LLM 调试输出（仅 Console 输出）
- 取消按钮可随时打断生成并回到首页（UI 回退动画生效；网络请求被 Abort）
- 生成完成后自动跳转到结果页，路由切换使用 out-in 动画，无突兀闪烁
- 遮罩层必须完全覆盖首页原界面（含 header、表单、按钮、背景装饰），不应透出可交互元素
- 每个执行阶段应有动态视觉反馈（阶段图标/动效切换/状态过渡），而不是仅靠日志文本堆叠

### Phase 6.1：动画基础框架（Transition + 可维护抽离）

- [x] T033 [US6] 【新增】创建全屏 Loading 过渡 composable：`frontend/src/composables/useFullscreenLoadingTransition.ts`（统一管理进入/退出动画、时长、easing、will-change 与 reduced-motion）**验收标准**：Home.vue 不直接写复杂动画逻辑；提供 `enter()`/`leave()`/`cancel()` API；默认 500-600ms 且 cubic-bezier(0.4, 0, 0.2, 1)。
- [x] T034 [P] [US6] 【新增】引入 GSAP（仅用于 transform/opacity 动画）：更新 `frontend/package.json` 并在 `useFullscreenLoadingTransition.ts` 中封装使用（避免散落到视图）**验收标准**：构建通过；动画仅涉及 opacity/transform/filter，不触发频繁 layout。
- [x] T035 [US6] 【修改】在 `frontend/src/App.vue` 为 `<router-view />` 增加 out-in 过渡容器（Transition mode=out-in，提供基础淡入淡出或轻微位移动画）**验收标准**：从首页→结果页、结果页→首页均有平滑过渡；不影响现有布局。

### Phase 6.2：Loading 组件与进度环（全屏遮罩 + 现代 UI）

- [x] T036 [US6] 【新增】创建全屏 Loading 组件：`frontend/src/components/FullscreenLoading.vue`（fixed 全屏、半透明遮罩、backdrop-blur-xl、呼吸光效渐变背景、中心区布局）**验收标准**：移动端适配良好；使用 transform/opacity 动画；包含取消按钮位。
- [x] T037 [P] [US6] 【新增】创建 SVG 进度环组件：`frontend/src/components/ProgressRing.vue`（支持 percent 数字平滑过渡、stroke-dashoffset 动画）**验收标准**：进度更新平滑；60fps；不会频繁重排。
- [x] T038 [US6] 【修改】在 `frontend/src/views/Home.vue` 接入 `FullscreenLoading.vue`（点击“生成旅途”后进入全屏 Loading 状态，并与 composable 动画联动）**验收标准**：点击按钮→500-600ms 动画过渡→全屏 Loading；遮罩层覆盖 header/表单/按钮。

### Phase 6.3：状态管理与实时日志（用户友好，隐藏调试）

- [x] T039 [US6] 【修改】在 `frontend/src/services/api.ts` 的 `streamTravelPlanByLocation` 增加“业务步骤日志”抽象（仅输出 progress/step/log；禁止把 llm_debug 发到 UI，改为 `console.debug`）**验收标准**：UI 侧拿不到 llm_debug；Console 仍可看到调试；不破坏现有 SSE 解析。
- [x] T040 [US6] 【修改】在 `frontend/src/views/Home.vue` 将实时日志改为“用户友好日志”（仅展示关键业务步骤，例如：连接服务/生成策略/检索候选/生成初稿/反思优化/规范化/保存结果）**验收标准**：日志简洁、稳定、不包含 LLM 原始输出；条数限制与滚动性能良好。
- [x] T041 [P] [US6] 【新增】创建日志格式化工具：`frontend/src/utils/loading-log-format.ts`（把 step/progress/status 映射为“安心感强”的短文案）**验收标准**：同一事件输出文案一致；支持中英/emoji 可选但默认克制；易扩展。

### Phase 6.4：取消逻辑与优雅回退（Abort + UI 退场）

- [x] T042 [US6] 【修改】为 `streamTravelPlanByLocation` 增加 AbortController 支持：允许 Home.vue 在取消时中断 fetch stream（新增可选参数 `signal` 或返回 `cancel()`）**验收标准**：取消后网络请求停止；不会继续推送进度；不会触发未处理异常。
- [x] T043 [US6] 【修改】在 `frontend/src/views/Home.vue` 实现“取消生成”按钮：触发 `AbortController.abort()` + 退场动画 + 状态复位**验收标准**：任何阶段可取消；UI 退回首页自然；用户输入不丢失；可再次点击生成。

### Phase 6.5：性能与测试（移动端优先）

- [x] T044 [P] [US6] 【新增】为动画 composable 补充单元测试：`frontend/tests/unit/useFullscreenLoadingTransition.spec.ts`（至少验证 API、时长、reduced-motion 分支）**验收标准**：测试稳定可跑；覆盖核心分支。
- [x] T045 [US6] 【新增】补充 E2E 或集成测试场景：`frontend/tests/e2e/home-loading-transition.spec.ts`（生成→loading→取消→再次生成→完成跳转）**验收标准**：可自动化验证关键路径；失败时定位清晰。

### Phase 6.6：遮罩完全覆盖与分阶段动态动画（新增）

- [x] T046 [US6] 【修改】强化 `frontend/src/components/FullscreenLoading.vue` 的覆盖层结构与交互屏蔽（全屏固定定位、最高层级、pointer-events 管控、锁定背景滚动），确保生成中原界面不可见且不可点击。**验收标准**：遮罩层在不同分辨率与滚动位置下都完全覆盖；Header/表单/按钮无法被点击穿透；取消后恢复正常滚动。
- [x] T047 [P] [US6] 【新增】创建阶段动画配置与状态映射：`frontend/src/utils/loading-stage-animation.ts`（定义 strategy/generation/reflection/normalizing/saving/done 各阶段的图标、动画 key、过渡时长、文案映射）。**验收标准**：同一阶段视觉表现一致；阶段切换有平滑过渡；支持后续扩展新阶段。
- [x] T048 [US6] 【修改】在 `frontend/src/components/FullscreenLoading.vue` 接入阶段动态视图（替代“仅日志框”主表现），根据阶段展示不同动画状态卡片（例如脉冲、流光、进度节奏变化）。**验收标准**：用户主要看到动态阶段反馈而非纯日志；阶段切换无跳变；低性能设备仍保持流畅。
- [x] T049 [US6] 【修改】在 `frontend/src/views/Home.vue` 与 `frontend/src/services/api.ts` 增加阶段状态驱动（把 SSE `step/progress` 映射为统一 `currentStage`），并限制日志仅做辅助信息。**验收标准**：阶段动画与后端步骤一致；日志数量受控；UI 不再依赖日志文本表达主要进度。
- [x] T050 [P] [US6] 【新增】补充覆盖与阶段动画测试：`frontend/tests/e2e/home-loading-transition.spec.ts` 与 `frontend/tests/unit/loading-stage-animation.spec.ts`，覆盖“遮罩完全覆盖、阶段切换动画、取消恢复”场景。**验收标准**：自动化可验证覆盖和阶段动效主路径；失败时可定位到阶段映射或动画逻辑。

### Phase 6.7：生成中小对话框深色主题修正（新增）

- [x] T051 [US6] 【修改】将生成中的小对话框（`frontend/src/components/FullscreenLoading.vue` 的中心内容卡片与日志容器）改为深色主题（深底 + 高可读文字 + 适配边框/阴影），减少透明感导致的视觉违和。**验收标准**：小对话框主体不再呈现浅色透明白卡；在深色遮罩背景上层次清晰；主要文字与状态信息对比度可读。
- [x] T052 [P] [US6] 【新增】补充视觉回归验证：`frontend/tests/e2e/home-loading-transition.spec.ts` 增加对深色主题 class/样式存在性的断言（或快照断言）。**验收标准**：自动化可检测小对话框已切换为深色主题；避免后续样式回退成透明浅色。

**依赖关系**：
- T038 依赖 T033、T036、T037
- T039/T040 依赖现有 `frontend/src/services/api.ts` SSE 流
- T042 依赖 T039（避免取消后 debug/UI 泄漏）
- T043 依赖 T033、T042
- T035 建议在 T038 前完成（保证跳转动画一致）
- T046 依赖 T036、T038（先有基础全屏 Loading 再强化覆盖隔离）
- T048 依赖 T047（先完成阶段动画配置）
- T049 依赖 T039、T041（先完成日志/步骤抽象）
- T050 依赖 T046、T048、T049（覆盖与阶段动效都完成后测试）
- T051 依赖 T046、T048（在完成覆盖层与阶段主视图后统一调整主题）
- T052 依赖 T051（主题改造完成后补回归）

---

## 依赖与执行顺序

### 阶段依赖

- **Phase 0（紧急修复）**：优先执行，先解决长行程超时问题。
- **Phase 1（基础设施与核心数据层）**：可在 Phase 0 修复后立即开始，是后续所有任务的前提。
- **Phase 2（结果页核心闭环）**：依赖 Phase 1 完成后开始。
- **Phase 3（智能行程优化）**：依赖 Phase 1 完成后开始，可与 Phase 2 并行推进部分任务。
- **Phase 4（地图联动与增强）**：依赖 Phase 2 的核心结果页能力。
- **Phase 5（边缘案例与质量收尾）**：依赖前面核心能力完成后进行。

### 当前最高优先级说明

- 目前优先级最高的是 **Phase 0 的长行程超时修复**。
- 该问题应先于规范文档细化、视觉增强和故事化浏览等工作处理。
- 先保证 4 天游程及以上可稳定生成，再继续推进结果页与优化能力。

### 用户故事依赖

- **US1（智能行程优化）**：依赖统一类型、规范化层与优化服务基础。
- **US2（查看与调整结果）**：依赖规范化层、编辑状态与结果页重构。
- **US3（深链导航）**：依赖标准化地点结构与结果页选中状态。
- **US4（导出分享）**：依赖标准化行程结构与导出服务。
- **US5（跨设备体验）**：依赖结果页重构与移动端布局优化。

### 阶段内执行原则

- 类型与数据模型先于服务实现。
- 服务先于页面集成。
- 页面集成先于增强特性。
- 测试尽量先写并验证失败，再实现。
- 同一阶段中，不同文件、无直接依赖的任务可并行。

### 可并行机会

- 所有带 `[P]` 的任务可并行执行，只要修改不同文件且不存在依赖。
- `itinerary-normalizer`、`itinerary-persistence`、`itinerary-helpers`、`itinerary-optimizer` 的基础工作可并行推进。
- `deep-link-service` 与 `export-service` 可在规范化层稳定后并行实现。
- `useItineraryEditing`、`useResultPage`、`useMapState` 可在类型层与规范化层准备好后并行开发。

---

## 实施策略

### MVP 优先

1. 先完成 Phase 0：长行程超时修复
2. 完成 Phase 1：基础设施与核心数据层
3. 完成 Phase 2：结果页核心闭环
4. 完成 Phase 3：智能行程优化
5. **暂停并验证**：确保生成、查看、编辑、保存、导航、导出都可独立工作

### 增量交付

1. 先解决超时与稳定性问题
2. 再完成规范化层，保证最小可用版本
3. 然后接通结果页闭环
4. 再加入智能优化与预算约束
5. 最后增强地图、故事化浏览与边缘案例处理

### 并行团队策略

如果有多个开发者：

1. 先共同完成 Phase 0 与 Phase 1
2. 基础稳定后可分工：
   - 开发者 A：结果页重构与编辑保存
   - 开发者 B：深链与导出服务
   - 开发者 C：智能行程优化与预算约束
   - 开发者 D：地图联动与 E2E 测试

---

## 说明

- `[P]` 表示可并行执行的任务
- `[USx]` 表示任务对应的用户故事
- 任务按“先紧急修复、后基础、再闭环、再增强、最后收尾”的顺序组织
- 所有核心任务都应优先复用现有 `Result.vue`，避免一次性重构整个前端
- 任何新任务如果引入新的文件，都应在任务描述中明确文件路径

---

## Phase 7：用户故事 7 - 旅程详情页定制化海报（Priority: P1）

**目标**：在旅程详情页新增“定制化海报”区域，基于当前旅程真实图片（景点/餐饮/活动）提供沉浸式故事化动画浏览体验，并保持移动端优先与高性能。

**独立验收**：
- 海报仅使用当前旅程真实图片，不使用占位图/通用素材
- 支持移动端丝滑浏览（滑动、全屏、放大），低端设备保持可用且接近 60fps
- 动画具备故事感（视差/淡入淡出/融合/缓慢缩放/卡片翻转中至少 3 种组合）
- LLM 调试信息仅在 console，不出现在 UI

### Phase 7.1：海报数据准备与图片处理

- [x] T053 [US7] 【新增】创建海报数据模型文件 `frontend/src/types/poster.ts`，定义 `PosterFrame`、`PosterStory`、`PosterAssetState`，并与现有 `TripPlan/DayPlan` 结构建立映射字段。**验收标准**：类型可被组件与 composable 复用；TypeScript 严格检查通过。
- [x] T054 [US7] 【新增】创建海报数据适配器 `frontend/src/services/poster-data-service.ts`，从 `Result.vue` 当前行程数据中提取真实图片（景点/餐饮/活动）并去重排序。**验收标准**：空图片条目被过滤；按天/时间排序稳定；无占位图混入。
- [x] T055 [P] [US7] 【新增】创建图片预加载与尺寸优化工具 `frontend/src/utils/poster-image-pipeline.ts`，负责懒加载、解码、优先级与失败回退策略。**验收标准**：首屏海报可快速渲染；失败图片有无打断回退；主线程阻塞受控。
- [x] T056 [P] [US7] 【新增】补充海报数据单测 `frontend/tests/unit/poster-data-service.spec.ts`，覆盖“无图/少图/多图/重复图”场景。**验收标准**：数据提取稳定；不依赖 UI 组件。

### Phase 7.2：海报组件与基础布局

- [x] T057 [US7] 【新增】创建海报主组件 `frontend/src/components/poster/TripPosterGallery.vue`（移动端优先布局，支持纵向故事流与横向卡片轨道）。**验收标准**：在手机视口下布局完整；与详情页主内容不冲突。
- [ ] T058 [P] [US7] 【新增】创建海报全屏查看组件 `frontend/src/components/poster/TripPosterLightbox.vue`（左右滑动、点击放大、关闭返回）。**验收标准**：可独立浏览；交互路径清晰；关闭后状态恢复。
- [x] T059 [P] [US7] 【新增】创建海报项组件 `frontend/src/components/poster/PosterFrameCard.vue`（标题、时间、地点标签、图片层融合）。**验收标准**：卡片信息可读；深浅模式都可用。
- [x] T060 [US7] 【修改】在 `frontend/src/views/Result.vue` 新增“定制化海报”区域骨架并接入 `TripPosterGallery`。**验收标准**：区域位置明确；不影响现有预算/地图/日程模块。

### Phase 7.3：精美动画实现（故事感）

- [ ] T061 [US7] 【新增】创建动画 composable `frontend/src/composables/usePosterStoryMotion.ts`，封装视差滚动、淡入淡出、慢速缩放、卡片翻转等动画状态机。**验收标准**：动画逻辑与视图解耦；提供可测试 API。
- [ ] T062 [P] [US7] 【新增】创建动画配置映射 `frontend/src/utils/poster-motion-presets.ts`，按设备性能档位切换动画强度（high/medium/low）。**验收标准**：低端设备自动降级；视觉连续性不破坏。
- [ ] T063 [US7] 【修改】在 `TripPosterGallery.vue` 与 `PosterFrameCard.vue` 接入故事化动画（至少 3 种组合动画），并支持 `prefers-reduced-motion`。**验收标准**：动画流畅、过渡自然；无明显掉帧与闪烁。
- [ ] T064 [P] [US7] 【新增】新增动画单测 `frontend/tests/unit/usePosterStoryMotion.spec.ts`，验证时序、状态切换与 reduced-motion 分支。**验收标准**：核心分支可自动化覆盖。

### Phase 7.4：详情页集成与交互完善

- [ ] T065 [US7] 【修改】在 `frontend/src/views/Result.vue` 接入全屏查看、左右滑动、点击放大与返回锚点，保持用户浏览闭环。**验收标准**：详情页→海报→全屏→返回流程自然；用户上下文不丢失。
- [ ] T066 [P] [US7] 【修改】扩展 `frontend/src/services/api.ts` 日志策略（海报相关仅业务日志；LLM debug 继续仅 console）。**验收标准**：UI 无调试噪音；控制台仍可追踪问题。
- [ ] T067 [P] [US7] 【新增】创建海报交互状态 composable `frontend/src/composables/usePosterInteraction.ts`（手势、索引、缩放状态、全屏开关）。**验收标准**：交互状态集中管理；组件间通信清晰。
- [ ] T068 [US7] 【修改】优化 `frontend/src/views/Result.vue` 与海报组件之间的数据桥接，优先复用现有行程与图片逻辑。**验收标准**：无重复请求；不引入新的数据源分叉。

### Phase 7.5：性能优化、边缘案例与测试

- [ ] T069 [US7] 【新增】创建性能守护工具 `frontend/src/utils/poster-performance-guard.ts`，实现帧率监测与动画降级触发。**验收标准**：低端设备可自动降级至轻量动画；不卡主线程。
- [ ] T070 [P] [US7] 【新增】补充边缘场景处理 `frontend/src/components/poster/TripPosterGallery.vue`（无图、单图、图片加载失败、超长行程）。**验收标准**：所有场景可用；无空白崩溃。
- [ ] T071 [P] [US7] 【新增】补充 E2E 场景 `frontend/tests/e2e/trip-poster.spec.ts`（详情页进入海报→滑动→放大→全屏关闭→返回原位置）。**验收标准**：关键路径自动化通过；失败定位清晰。
- [ ] T072 [US7] 【修改】更新 `specs/001-smart-itinerary-optimization/quickstart.md`，新增海报功能验收步骤与性能检查命令。**验收标准**：开发者可按文档复现并验证海报功能。

**依赖关系**：
- T054 依赖 T053
- T057/T058/T059 依赖 T053、T054
- T060 依赖 T057
- T063 依赖 T061、T062、T059
- T065 依赖 T058、T060、T063
- T068 依赖 T054、T060
- T069 依赖 T063
- T070 依赖 T057、T055
- T071 依赖 T065、T070
- T072 依赖 T071
