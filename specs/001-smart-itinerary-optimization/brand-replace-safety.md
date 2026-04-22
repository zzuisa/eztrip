# RogueTrip 品牌替换安全清单

## 目标

在执行 EZTrip/HelloAgents -> RogueTrip 文本替换时，确保“全量但不误伤”。

## 可替换范围（白名单）

- 用户可见文案：页面标题、导航标题、README、说明文档
- 元数据：`index.html` title/meta、`package.json` name/description
- 品牌常量与注释中的项目名称
- Spec Kit 文档中的品牌称谓

## 禁止替换范围（黑名单）

- 第三方库名称与包名（如 `vue`、`vite`、`mapbox-gl`）
- API 路径、路由前缀、接口字段名
- 已落地数据目录名与历史兼容路径（除非明确迁移）
- 与业务语义绑定的变量名（非品牌语义）
- 证书、密钥、环境变量键名

## 执行策略

1. 先新增品牌常量并替换 UI 显示层。
2. 再替换配置与文档中的品牌词。
3. 最后执行全局搜索复核，人工确认高风险命中。

## 推荐复核关键词

- `EZTrip`
- `HelloAgents`
- `helloagents`

## 验收标准

- 用户可见品牌文案统一为 `RogueTrip`
- 无第三方依赖、路径、协议字段被误改
- 构建与测试通过

