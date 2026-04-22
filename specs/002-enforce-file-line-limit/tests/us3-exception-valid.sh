#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
WORK_DIR="${ROOT_DIR}/specs/002-enforce-file-line-limit/tests/.tmp-us3-valid"
RULE_FILE="${WORK_DIR}/rule.json"
EXC_FILE="${WORK_DIR}/exceptions.json"
TARGET_FILE="${WORK_DIR}/target.txt"
TARGET_REL="specs/002-enforce-file-line-limit/tests/.tmp-us3-valid/target.txt"

mkdir -p "${WORK_DIR}"
: > "${TARGET_FILE}"
for i in $(seq 1 550); do echo "line-${i}" >> "${TARGET_FILE}"; done

cat > "${RULE_FILE}" <<EOF
{
  "enabled": true,
  "maxLines": 500,
  "includePaths": ["specs/002-enforce-file-line-limit/tests/.tmp-us3-valid/*.txt"],
  "excludePaths": []
}
EOF

cat > "${EXC_FILE}" <<EOF
{
  "exceptions": [
    {
      "filePath": "${TARGET_REL}",
      "reason": "test exception",
      "owner": "qa",
      "expiresAt": "2099-01-01T00:00:00Z"
    }
  ]
}
EOF

bash "${ROOT_DIR}/.specify/scripts/bash/check-file-line-limit.sh" \
  --target "${TARGET_REL}" \
  --rule-file "${RULE_FILE}" \
  --exceptions-file "${EXC_FILE}" >/tmp/us3-exception-valid.log 2>&1

grep -q "PASS" /tmp/us3-exception-valid.log
echo "[PASS] us3-exception-valid"
