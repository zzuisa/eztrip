#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
WORK_DIR="${ROOT_DIR}/specs/002-enforce-file-line-limit/tests/.tmp-us1-pass"
RULE_FILE="${WORK_DIR}/rule.json"
EXC_FILE="${WORK_DIR}/exceptions.json"
TARGET_REL="specs/002-enforce-file-line-limit/tests/.tmp-us1-pass/target.txt"

mkdir -p "${WORK_DIR}"
rm -f "${WORK_DIR}/target.txt"
for i in $(seq 1 500); do echo "line-${i}" >> "${WORK_DIR}/target.txt"; done

cat > "${RULE_FILE}" <<EOF
{
  "enabled": true,
  "maxLines": 500,
  "includePaths": ["specs/002-enforce-file-line-limit/tests/.tmp-us1-pass/*.txt"],
  "excludePaths": []
}
EOF

cat > "${EXC_FILE}" <<EOF
{ "exceptions": [] }
EOF

bash "${ROOT_DIR}/.specify/scripts/bash/check-file-line-limit.sh" \
  --target "${TARGET_REL}" \
  --rule-file "${RULE_FILE}" \
  --exceptions-file "${EXC_FILE}" \
  --output text >/tmp/us1-pass-under-limit.log 2>&1

grep -q "PASS" /tmp/us1-pass-under-limit.log
echo "[PASS] us1-pass-under-limit"
