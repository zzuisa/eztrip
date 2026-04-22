# Data Model: Enforce File Line Limit

## Entity: LineLimitRule

- **Description**: 行数治理规则定义，描述阈值与适用范围。  
- **Fields**:
  - `maxLines` (number, required): 单文件最大允许行数（当前为 500）
  - `includePaths` (string[], required): 受管控目录/文件匹配范围
  - `excludePaths` (string[], optional): 全局排除路径（如生成产物）
  - `enabled` (boolean, required): 规则是否启用
  - `updatedAt` (datetime, required): 最近更新时间

## Entity: ExceptionEntry

- **Description**: 例外清单条目，用于受控放宽个别文件限制。  
- **Fields**:
  - `filePath` (string, required, unique): 例外文件路径
  - `reason` (string, required): 允许例外的业务理由
  - `owner` (string, required): 维护责任人
  - `expiresAt` (datetime, optional): 例外到期时间
  - `updatedAt` (datetime, required): 最近更新时间

## Entity: FileScanResult

- **Description**: 单次扫描中每个文件的检查结果。  
- **Fields**:
  - `filePath` (string, required)
  - `lineCount` (number, required)
  - `maxLines` (number, required)
  - `isException` (boolean, required)
  - `status` (enum: `pass` | `fail`, required)
  - `overflowLines` (number, required): 超限行数（未超限时为 0）

## Entity: CheckReport

- **Description**: 单次检查的聚合输出。  
- **Fields**:
  - `checkedAt` (datetime, required)
  - `checkedFiles` (number, required)
  - `failedFiles` (number, required)
  - `results` (FileScanResult[], required)
  - `exitCode` (number, required): 0 表示通过，非 0 表示失败

## Relationships

- `LineLimitRule` 1:N `FileScanResult`（单条规则应用于多文件）  
- `ExceptionEntry` 1:N `FileScanResult`（例外条目可影响多个扫描批次中的同一文件）  
- `CheckReport` 1:N `FileScanResult`（一份报告包含多条文件结果）

## Validation Rules

- `maxLines` 必须为正整数，且当前规范固定为 500。  
- `filePath` 必须是仓库内相对路径，禁止越界路径。  
- `overflowLines = max(lineCount - maxLines, 0)`。  
- `status = fail` 当且仅当 `lineCount > maxLines AND isException = false`。  
- 例外条目若过期，应在检查时视为无效并提示。
