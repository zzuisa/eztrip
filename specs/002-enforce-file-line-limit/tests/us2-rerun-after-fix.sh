#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
WORK_DIR="${ROOT_DIR}/specs/002-enforce-file-line-limit/tests/.tmp-us2-rerun"
RULE_FILE="${WORK_DIR}/rule.json"
EXC_FILE="${WORK_DIR}/exceptions.json"
TARGET_REL="specs/002-enforce-file-line-limit/tests/.tmp-us2-rerun/target.txt"
TARGET_FILE="${WORK_DIR}/target.txt"

mkdir -p "${WORK_DIR}"
: > "${TARGET_FILE}"
for i in $(seq 1 520); do echo "line-${i}" >> "${TARGET_FILE}"; done

cat > "${RULE_FILE}" <<EOF
{
  "enabled": true,
  "maxLines": 500,
  "includePaths": ["specs/002-enforce-file-line-limit/tests/.tmp-us2-rerun/*.txt"],
  "excludePaths": []
}
EOF
cat > "${EXC_FILE}" <<EOF
{ "exceptions": [] }
EOF

set +e
bash "${ROOT_DIR}/.specify/scripts/bash/check-file-line-limit.sh" \
  --target "${TARGET_REL}" \
  --rule-file "${RULE_FILE}" \
  --exceptions-file "${EXC_FILE}" >/tmp/us2-rerun-step1.log 2>&1
STEP1=$?
set -e
if [[ ${STEP1} -eq 0 ]]; then
  echo "[FAIL] step1 should fail before fix"
  exit 1
fi

head -n 500 "${TARGET_FILE}" > "${TARGET_FILE}.fixed"
mv "${TARGET_FILE}.fixed" "${TARGET_FILE}"

bash "${ROOT_DIR}/.specify/scripts/bash/check-file-line-limit.sh" \
  --target "${TARGET_REL}" \
  --rule-file "${RULE_FILE}" \
  --exceptions-file "${EXC_FILE}" >/tmp/us2-rerun-step2.log 2>&1

grep -q "PASS" /tmp/us2-rerun-step2.log
echo "[PASS] us2-rerun-after-fix"
