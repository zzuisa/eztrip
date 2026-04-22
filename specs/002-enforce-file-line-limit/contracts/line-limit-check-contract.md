# Contract: Line Limit Check

## Purpose

定义“单文件最大 500 行检查”的输入、输出和退出语义，确保本地与 CI 行为一致。

## Inputs

- **Rule Config**: 包含 `maxLines`、扫描范围、排除范围。  
- **Exception List**: 例外文件路径及理由。  
- **Target Revision**: 待检查文件集合（工作区或提交内容）。

## Output Schema

```json
{
  "checkedAt": "2026-04-22T10:00:00Z",
  "maxLines": 500,
  "checkedFiles": 120,
  "failedFiles": 2,
  "warnings": [],
  "results": [
    {
      "filePath": "frontend/src/views/Result.vue",
      "lineCount": 680,
      "maxLines": 500,
      "isException": false,
      "status": "fail",
      "overflowLines": 180
    }
  ]
}
```

## Exit Semantics

- `exitCode = 0`: 所有受管控文件通过，或仅存在有效例外文件超限。  
- `exitCode != 0`: 存在至少一个非例外超限文件，或配置无效导致无法可信执行检查。

## Ordering Rules

- `results` 应按“失败优先、超限差值降序、路径字典序”排序输出。  
- 同一份输入在不同环境应得到相同的排序结果。

## Error Contract

- 配置缺失/格式错误：必须返回可读错误信息并失败退出。  
- 无效例外路径：必须在输出中标注 warning，且不应被当作有效例外。  
- 扫描目标为空：允许通过，但需输出 `checkedFiles = 0`。
