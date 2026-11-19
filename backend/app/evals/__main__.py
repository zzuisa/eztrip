"""评测集命令行：对一批已保存的行程跑确定性评分（不调用任何模型 / 付费接口）。

    python -m app.evals                         # 评估 storage/travel_plans 下全部行程
    python -m app.evals --dir <目录> --top 8    # 指定目录；只列出分数最低的 8 个
    python -m app.evals --json                  # 机器可读输出
    python -m app.evals --baseline base.json    # 与上次保存的结果对比（分数下降 > 3 视为退步，退出码 1）
    python -m app.evals --save base.json        # 保存本次结果作为基线

固定用例放在 app/evals/cases/*.json（同样是行程 payload，附 {"expect": {"min_score": 80, "no": ["closed_day"], "has": ["overlap"]}}）。
"no" = 不该出现的问题，"has" = 必须检出的问题（用来保证评分器本身不会失灵）。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

from ..services.trip_quality import score_trip


def _load(path: Path) -> Dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return raw.get("payload") if isinstance(raw, dict) and isinstance(raw.get("payload"), dict) else raw


def evaluate(files: List[Path]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for f in files:
        try:
            p = _load(f)
            r = score_trip(p)
        except Exception as e:                      # noqa: BLE001
            out.append({"id": f.stem, "location": "?", "score": 0, "error": str(e), "issues": [], "metrics": {}})
            continue
        exp = p.get("expect") if isinstance(p.get("expect"), dict) else {}
        codes = {i["code"] for i in r["issues"]}
        failed = []
        if "min_score" in exp and r["score"] < exp["min_score"]:
            failed.append("score %d < %s" % (r["score"], exp["min_score"]))
        if "max_score" in exp and r["score"] > exp["max_score"]:
            failed.append("score %d > %s（评分器对明显有问题的行程打分过高）" % (r["score"], exp["max_score"]))
        failed += ["出现了不该有的 %s" % c for c in exp.get("no", []) if c in codes]
        failed += ["应当检出却没有检出 %s" % c for c in exp.get("has", []) if c not in codes]
        out.append({"id": f.stem, "location": p.get("location", ""), "days": r["metrics"].get("days", 0), **r, "expect_failed": failed})
    return out


def summarize(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    n = len(rows)
    by: Dict[str, int] = {}
    for r in rows:
        for i in r["issues"]:
            by[i["code"]] = by.get(i["code"], 0) + 1
    return {"count": n, "avg": round(sum(r["score"] for r in rows) / n, 1) if n else 0, "issues_by_code": dict(sorted(by.items(), key=lambda x: -x[1]))}


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="app.evals")
    root = Path(__file__).resolve().parents[2]
    ap.add_argument("--dir", default=str(root / "storage" / "travel_plans"))
    ap.add_argument("--cases", action="store_true", help="只跑 app/evals/cases 里的固定用例")
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--save")
    ap.add_argument("--baseline")
    a = ap.parse_args(argv)
    d = Path(__file__).resolve().parent / "cases" if a.cases else Path(a.dir)
    rows = evaluate(sorted(d.glob("*.json")))
    sm = summarize(rows)
    regress: List[str] = []
    if a.baseline:
        base = {r["id"]: r["score"] for r in json.loads(Path(a.baseline).read_text(encoding="utf-8")).get("rows", [])}
        regress = ["%s %s → %s" % (r["id"][:8], base[r["id"]], r["score"]) for r in rows if r["id"] in base and r["score"] < base[r["id"]] - 3]
    if a.save:
        Path(a.save).write_text(json.dumps({"summary": sm, "rows": [{"id": r["id"], "score": r["score"]} for r in rows]}, ensure_ascii=False), encoding="utf-8")
    if a.json:
        print(json.dumps({"summary": sm, "rows": rows, "regressions": regress}, ensure_ascii=False))
    else:
        print("行程 %d 个，平均 %.1f 分" % (sm["count"], sm["avg"]))
        print("问题类型：" + "，".join("%s×%d" % kv for kv in sm["issues_by_code"].items()))
        for r in sorted(rows, key=lambda x: x["score"])[: a.top]:
            print("%3d  %s  %s %dd  %s" % (r["score"], r["id"][:8], r["location"], r.get("days", 0), "；".join(i["text"] for i in r["issues"][:2])))
        for r in rows:
            if r.get("expect_failed"):
                print("用例未通过 %s：%s" % (r["id"], "，".join(r["expect_failed"])))
        for x in regress:
            print("退步：" + x)
    return 1 if regress or any(r.get("expect_failed") for r in rows) else 0


if __name__ == "__main__":
    sys.exit(main())

