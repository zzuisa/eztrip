#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
WORK_DIR="${ROOT_DIR}/specs/002-enforce-file-line-limit/tests/.tmp-us2-multi"
RULE_FILE="${WORK_DIR}/rule.json"
EXC_FILE="${WORK_DIR}/exceptions.json"
FILE_A="${ROOT_DIR}/specs/002-enforce-file-line-limit/test-fixtures/exact-500.txt"
FILE_B="${ROOT_DIR}/specs/002-enforce-file-line-limit/test-fixtures/over-501.txt"
REL_A="specs/002-enforce-file-line-limit/test-fixtures/exact-500.txt"
REL_B="specs/002-enforce-file-line-limit/test-fixtures/over-501.txt"
BAK_A="${WORK_DIR}/exact-500.bak"
BAK_B="${WORK_DIR}/over-501.bak"

mkdir -p "${WORK_DIR}"
cp "${FILE_A}" "${BAK_A}"
cp "${FILE_B}" "${BAK_B}"
trap 'cp "${BAK_A}" "${FILE_A}"; cp "${BAK_B}" "${FILE_B}"' EXIT

: > "${FILE_A}"
: > "${FILE_B}"
for i in $(seq 1 520); do echo "a-${i}" >> "${FILE_A}"; done
for i in $(seq 1 530); do echo "b-${i}" >> "${FILE_B}"; done

cat > "${RULE_FILE}" <<EOF
{
  "enabled": true,
  "maxLines": 500,
  "includePaths": ["specs/002-enforce-file-line-limit/test-fixtures/*.txt"],
  "excludePaths": []
}
EOF
cat > "${EXC_FILE}" <<EOF
{ "exceptions": [] }
EOF

set +e
OUT="$(bash "${ROOT_DIR}/.specify/scripts/bash/check-file-line-limit.sh" \
  --target "${REL_A}" \
  --target "${REL_B}" \
  --rule-file "${RULE_FILE}" \
  --exceptions-file "${EXC_FILE}" \
  --output text 2>&1)"
CODE=$?
set -e

if [[ ${CODE} -eq 0 ]]; then
  echo "[FAIL] expected failure for multiple over-limit files"
  exit 1
fi

echo "${OUT}" | grep -q "${REL_A}"
echo "${OUT}" | grep -q "${REL_B}"
echo "[PASS] us2-multi-file-report"
