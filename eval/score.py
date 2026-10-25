"""eval/results/*.jsonl을 정답과 비교해 방식별, 질문 유형별 점수를 낸다.

채점
- set    : 정답 집합과의 F1(정확히 맞으면 1.0)
- exact  : 첫 답이 정답과 같으면 1(대소문자, 앞뒤 공백 무시)
- number : 첫 답의 수치가 정답과 같으면 1

    python eval/score.py            # 표 출력 + eval/results/summary.md
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).parent


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", str(s)).strip().upper()


def score(grading: str, gold, pred: list[str]) -> float:
    if grading == "set":
        g, p = {norm(x) for x in gold}, {norm(x) for x in pred}
        if not g and not p:
            return 1.0
        tp = len(g & p)
        if tp == 0:
            return 0.0
        prec, rec = tp / len(p), tp / len(g)
        return 2 * prec * rec / (prec + rec)
    if not pred:
        return 0.0
    if grading == "number":
        try:
            return float(float(re.sub(r"[^\d.]", "", pred[0])) == float(gold))
        except ValueError:
            return 0.0
    return float(norm(pred[0]) == norm(gold))


def main() -> None:
    qs = {q["id"]: q for q in map(json.loads, (HERE / "questions.jsonl").open(encoding="utf-8"))}
    table: dict[str, dict[str, float]] = {}
    by_type: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    secs: dict[str, list[float]] = defaultdict(list)
    for path in sorted((HERE / "results").glob("*.jsonl")):
        name = path.stem
        for r in map(json.loads, path.open(encoding="utf-8")):
            q = qs[r["id"]]
            s = score(q["grading"], q["gold"], r.get("answer", []))
            table.setdefault(r["id"], {})[name] = s
            by_type[name][q["type"]].append(s)
            by_type[name]["ALL"].append(s)
            secs[name].append(r.get("seconds", 0))
    methods = sorted(by_type)
    lines = ["| 질문 | 유형 | " + " | ".join(methods) + " |", "|---|---|" + "---:|" * len(methods)]
    for qid, q in qs.items():
        cells = [f"{table.get(qid, {}).get(m, float('nan')):.2f}" for m in methods]
        lines.append(f"| {qid} | {q['type']} | " + " | ".join(cells) + " |")
    lines += ["", "| 유형 | " + " | ".join(methods) + " |", "|---|" + "---:|" * len(methods)]
    for t in ["lookup", "filter", "multi-hop", "aggregate", "text", "ALL"]:
        cells = []
        for m in methods:
            v = by_type[m].get(t, [])
            cells.append(f"{sum(v) / len(v):.2f} (n={len(v)})" if v else "-")
        lines.append(f"| {t} | " + " | ".join(cells) + " |")
    lines += ["", "| 평균 소요(초) | " + " | ".join(f"{sum(secs[m]) / len(secs[m]):.1f}" for m in methods) + " |"]
    md = "\n".join(lines)
    print(md)
    (HERE / "results" / "summary.md").write_text(md + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
