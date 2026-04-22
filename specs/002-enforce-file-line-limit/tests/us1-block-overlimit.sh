#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
WORK_DIR="${ROOT_DIR}/specs/002-enforce-file-line-limit/tests/.tmp-us1-over"
RULE_FILE="${WORK_DIR}/rule.json"
EXC_FILE="${WORK_DIR}/exceptions.json"
TARGET_REL="specs/002-enforce-file-line-limit/tests/.tmp-us1-over/target.txt"

mkdir -p "${WORK_DIR}"
rm -f "${WORK_DIR}/target.txt"
for i in $(seq 1 520); do echo "line-${i}" >> "${WORK_DIR}/target.txt"; done

cat > "${RULE_FILE}" <<EOF
{
  "enabled": true,
  "maxLines": 500,
  "includePaths": ["specs/002-enforce-file-line-limit/tests/.tmp-us1-over/*.txt"],
  "excludePaths": []
}
EOF

cat > "${EXC_FILE}" <<EOF
{ "exceptions": [] }
EOF

set +e
OUT="$(bash "${ROOT_DIR}/.specify/scripts/bash/check-file-line-limit.sh" \
  --target "${TARGET_REL}" \
  --rule-file "${RULE_FILE}" \
  --exceptions-file "${EXC_FILE}" \
  --output text 2>&1)"
CODE=$?
set -e

if [[ ${CODE} -eq 0 ]]; then
  echo "[FAIL] expected non-zero for over-limit file"
  exit 1
fi

echo "${OUT}" | grep -q "overflow="
echo "[PASS] us1-block-overlimit"
