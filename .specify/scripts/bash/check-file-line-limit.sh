#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
RULE_FILE="${ROOT_DIR}/.specify/line-limit/rule.json"
EXCEPTIONS_FILE="${ROOT_DIR}/.specify/line-limit/exceptions.json"
MODE="all"
TARGET_FILES=()
OUTPUT="text"

usage() {
  cat <<'EOF'
Usage: check-file-line-limit.sh [options]

Options:
  --mode <all|staged|changed>  Scan mode (default: all)
  --target <path>              Scan only one file
  --rule-file <path>           Override rule json path
  --exceptions-file <path>     Override exceptions json path
  --output <text|json>         Output format (default: text)
  -h, --help                   Show help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode) MODE="${2:-}"; shift 2 ;;
    --target) TARGET_FILES+=("${2:-}"); shift 2 ;;
    --rule-file) RULE_FILE="${2:-}"; shift 2 ;;
    --exceptions-file) EXCEPTIONS_FILE="${2:-}"; shift 2 ;;
    --output) OUTPUT="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage; exit 2 ;;
  esac
done

if [[ ! -f "${RULE_FILE}" ]]; then
  echo "[line-limit] ERROR: rule file not found: ${RULE_FILE}" >&2
  exit 2
fi

if [[ ! -f "${EXCEPTIONS_FILE}" ]]; then
  echo "[line-limit] ERROR: exceptions file not found: ${EXCEPTIONS_FILE}" >&2
  exit 2
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "[line-limit] ERROR: python3 is required" >&2
  exit 2
fi

TMP_FILES="$(mktemp)"
trap 'rm -f "${TMP_FILES}"' EXIT

if [[ ${#TARGET_FILES[@]} -gt 0 ]]; then
  printf '%s\n' "${TARGET_FILES[@]}" > "${TMP_FILES}"
else
  case "${MODE}" in
    staged)
      git -C "${ROOT_DIR}" diff --cached --name-only --diff-filter=ACMR > "${TMP_FILES}"
      ;;
    changed)
      git -C "${ROOT_DIR}" diff --name-only --diff-filter=ACMR > "${TMP_FILES}"
      ;;
    all)
      git -C "${ROOT_DIR}" ls-files > "${TMP_FILES}"
      ;;
    *)
      echo "[line-limit] ERROR: invalid mode: ${MODE}" >&2
      exit 2
      ;;
  esac
fi

python3 - "${ROOT_DIR}" "${RULE_FILE}" "${EXCEPTIONS_FILE}" "${TMP_FILES}" "${OUTPUT}" <<'PY'
import datetime as dt
import fnmatch
import json
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
rule_file = pathlib.Path(sys.argv[2])
exceptions_file = pathlib.Path(sys.argv[3])
files_file = pathlib.Path(sys.argv[4])
output = sys.argv[5]

def load_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[line-limit] ERROR: invalid json in {path}: {exc}", file=sys.stderr)
        sys.exit(2)

rule = load_json(rule_file)
exc_cfg = load_json(exceptions_file)

enabled = bool(rule.get("enabled", True))
max_lines = int(rule.get("maxLines", 500))
includes = rule.get("includePaths", [])
excludes = rule.get("excludePaths", [])
exceptions = exc_cfg.get("exceptions", [])

if max_lines <= 0:
    print("[line-limit] ERROR: maxLines must be a positive integer", file=sys.stderr)
    sys.exit(2)

if not isinstance(includes, list) or not includes:
    print("[line-limit] ERROR: includePaths must be a non-empty list", file=sys.stderr)
    sys.exit(2)

raw_files = [ln.strip() for ln in files_file.read_text(encoding="utf-8").splitlines() if ln.strip()]
raw_files = list(dict.fromkeys(raw_files))

def match_any(path_str, patterns):
    return any(fnmatch.fnmatch(path_str, p) for p in patterns)

def iso_to_dt(value):
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None

warnings = []
exception_map = {}
now = dt.datetime.now(dt.timezone.utc)

for entry in exceptions:
    p = entry.get("filePath")
    if not p or not isinstance(p, str):
        warnings.append("Invalid exception entry: missing filePath")
        continue
    expires = iso_to_dt(entry.get("expiresAt"))
    if entry.get("expiresAt") and expires is None:
        warnings.append(f"Invalid exception date format: {p}")
        continue
    if expires and expires < now:
        warnings.append(f"Expired exception ignored: {p}")
        continue
    abs_path = root / p
    if not abs_path.exists():
        warnings.append(f"Exception path does not exist: {p}")
        continue
    exception_map[p] = entry

results = []
checked_files = 0
failed_files = 0

for path_str in raw_files:
    rel = path_str.replace("\\", "/")
    if not enabled:
        continue
    if not match_any(rel, includes):
        continue
    if match_any(rel, excludes):
        continue

    abs_path = root / rel
    if not abs_path.exists() or not abs_path.is_file():
        continue

    try:
        content = abs_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        # ignore binary
        continue
    except Exception as exc:
        warnings.append(f"Cannot read file {rel}: {exc}")
        continue

    checked_files += 1
    line_count = len(content.splitlines())
    is_exception = rel in exception_map
    overflow = max(line_count - max_lines, 0)
    status = "pass"
    if overflow > 0 and not is_exception:
        status = "fail"
        failed_files += 1
    results.append(
        {
            "filePath": rel,
            "lineCount": line_count,
            "maxLines": max_lines,
            "isException": is_exception,
            "status": status,
            "overflowLines": overflow,
        }
    )

results.sort(key=lambda x: (x["status"] != "fail", -x["overflowLines"], x["filePath"]))
report = {
    "checkedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
    "maxLines": max_lines,
    "checkedFiles": checked_files,
    "failedFiles": failed_files,
    "warnings": warnings,
    "results": results,
}

if output == "json":
    print(json.dumps(report, ensure_ascii=False, indent=2))
else:
    print(f"[line-limit] checked={checked_files} failed={failed_files} maxLines={max_lines}")
    for w in warnings:
        print(f"[line-limit][WARN] {w}")
    if failed_files:
        print("[line-limit] Violations:")
        for r in results:
            if r["status"] == "fail":
                print(
                    f"  - {r['filePath']} lines={r['lineCount']} "
                    f"limit={r['maxLines']} overflow={r['overflowLines']}"
                )
                print("    suggestion: split file into smaller modules or add reviewed exception entry")
    else:
        print("[line-limit] PASS")

sys.exit(1 if failed_files else 0)
PY
