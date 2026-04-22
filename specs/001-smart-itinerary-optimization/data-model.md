# 数据模型：智能行程优化与结果页升级

## TripRequest
表示用户的行程生成输入。

### 字段
- `destination`：目的城市或区域
- `travelDays`：旅行天数
- `budgetMin`：预算下限
- `budgetMax`：预算上限
- `preferences`：旅行偏好列表
- `weatherPreference`：天气或室内/室外偏好
- `dietaryRestrictions`：饮食限制
- `startDate` / `endDate`：可选的行程日期

### 校验
- 旅行天数必须大于 0
- 预算范围必须有效
- 偏好列表可为空，但不能包含脏数据

### 状态
- 由表单创建
- 传给优化服务

## OptimizedItinerary
标准化后的生成结果。

### 字段
- `city`
- `startDate`
- `endDate`
- `days[]`
- `budgetSummary`
- `suggestions`
- `warnings`

### 关系
- 拥有多个 `TripDay`
- 被结果页、深链服务、导出服务消费

### 校验
- 总花费必须满足预算规则
- 即使数据不完整也应可渲染

## TripDay
行程中的单日计划。

### 字段
- `dayIndex`
- `date`
- `description`
- `transportation`
- `accommodation`
- `attractions[]`
- `meals[]`
- `dayCostEstimate`

### 关系
- 属于一个 `OptimizedItinerary`
- 包含供地图和导出使用的地点

### 校验
- 天数索引必须稳定
- 当日活动时长应限制在允许范围内

## PlaceItem
可展示、可导航、可导出的地点。

### 字段
- `id`
- `kind`（`attraction` | `meal` | `snack` | `other`）
- `name`
- `address`
- `location`
- `description`
- `ticketPrice`
- `estimatedCost`
- `visitDuration`
- `routeDescription`
- `timeSlot`

### 校验
- 位置可选用于展示，但生成导航时必须存在
- 名称不能为空

## BudgetSummary
整个行程的成本拆分。

### 字段
- `attractions`
- `hotels`
- `meals`
- `transport`
- `total`
- `currency`

### 校验
- 缺失值默认 0
- 总价尽量与已知分项保持一致

## NavigationLink
用于生成 Google Maps 深链的路线结构。

### 字段
- `items[]`
- `travelMode`
- `destination`
- `waypoints`
- `sourceContext`

### 校验
- 至少要有一个可导航位置
- 顺序必须与当前行程顺序一致

## ResultViewState
结果页 UI 状态。

### 字段
- `activeSection`
- `activeDays`
- `selectedPlaceKey`
- `editMode`
- `deepLinkVisible`
- `mapStory`
- `exportStatus`

### 关系
- 引用当前标准化后的行程
- 驱动地图、选中状态和导出行为

### 状态转换
- 查看 → 编辑：用户进入编辑模式
- 编辑 → 已保存：用户保存修改
- 已保存 → 已恢复：刷新后通过浏览器存储恢复
- 任意状态 → 回退：地图或导出失败时回退
