"""eval/results/{method}_{model}_r{N}.jsonl을 정답과 비교해 모델 x 방식별 점수를 낸다.

채점
- set    : 정답 집합과의 F1(정확히 맞으면 1.0)
- exact  : 첫 답이 정답과 같으면 1(대소문자, 앞뒤 공백 무시)
- number : 첫 답의 수치가 정답과 같으면 1

여러 회차가 있으면 회차별 전체 점수의 평균과 최소~최대를 낸다. 24문항을 다 마친 회차만 센다.

    python eval/score.py            # 표 출력 + eval/results/summary.md
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from statistics import mean

HERE = Path(__file__).parent
TYPES = ["lookup", "filter", "multi-hop", "aggregate", "text"]
TYPE_KO = {"lookup": "조회", "filter": "조건 검색", "multi-hop": "여러 단계", "aggregate": "집계", "text": "문장 이해"}
MODEL_ORDER = ["haiku", "sonnet", "opus", "fable"]
MODEL_NAME = {"haiku": "Haiku 5.5", "sonnet": "Sonnet 5.5", "opus": "Opus 5.5", "fable": "Fable 5.1"}
METHOD_NAME = {"graph_direct": "그래프 질의", "hybrid": "하이브리드 RAG", "graph": "그래프(LLM 답변)", "vector": "벡터 RAG"}


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


def load():
    qs = {q["id"]: q for q in map(json.loads, (HERE / "questions.jsonl").open(encoding="utf-8"))}
    runs = defaultdict(dict)  # (method, model) -> run -> {qid: record+score}
    for path in sorted((HERE / "results").glob("*_r*.jsonl")):
        m = re.fullmatch(r"(.+)_([a-z0-9-]+)_r(\d+)", path.stem)
        if not m:
            continue
        method, model, run = m.group(1), m.group(2), int(m.group(3))
        recs = {}
        for r in map(json.loads, path.open(encoding="utf-8")):
            q = qs[r["id"]]
            r["score"] = score(q["grading"], q["gold"], r.get("answer", []))
            recs[r["id"]] = r
        if len(recs) == len(qs):
            runs[(method, model)][run] = recs
    return qs, runs


def main() -> None:
    qs, runs = load()
    keys = sorted(runs, key=lambda k: (k[0] != "graph_direct", MODEL_ORDER.index(k[1]) if k[1] in MODEL_ORDER else 9))
    out = []

    out += ["### 모델 x 방식 (질문 24개, 회차 평균)", "",
            "| 방식 | 모델 | 회차 | 전체 평균 (최소~최대) | " + " | ".join(TYPE_KO[t] for t in TYPES) +
            " | 문항당 초 | 문항당 비용(USD, API 환산) |",
            "|---|---|---:|---:|" + "---:|" * len(TYPES) + "---:|---:|"]
    for k in keys:
        rs = runs[k]
        totals = [mean(r["score"] for r in recs.values()) for recs in rs.values()]
        by_type = []
        for t in TYPES:
            vals = [mean(r["score"] for r in recs.values() if qs[r["id"]]["type"] == t) for recs in rs.values()]
            by_type.append(f"{mean(vals):.2f}")
        secs = mean(r["seconds"] for recs in rs.values() for r in recs.values())
        costs = [r.get("cost_usd") for recs in rs.values() for r in recs.values() if r.get("cost_usd") is not None]
        rng = f"({min(totals):.2f}~{max(totals):.2f})" if len(totals) > 1 else ""
        out.append(f"| {METHOD_NAME.get(k[0], k[0])} | {MODEL_NAME.get(k[1], k[1])} | {len(rs)} | {mean(totals):.2f} {rng} | "
                   + " | ".join(by_type) + f" | {secs:.1f} | {mean(costs):.4f} |" if costs else
                   f"| {METHOD_NAME.get(k[0], k[0])} | {MODEL_NAME.get(k[1], k[1])} | {len(rs)} | {mean(totals):.2f} {rng} | "
                   + " | ".join(by_type) + f" | {secs:.1f} | - |")

    out += ["", "### 질문별: 회차 중 만점을 받은 횟수", "",
            "| 질문 | 유형 | " + " | ".join(f"{METHOD_NAME.get(k[0], k[0])} {MODEL_NAME.get(k[1], k[1])}" for k in keys) + " |",
            "|---|---|" + "---:|" * len(keys)]
    for qid, q in qs.items():
        cells = []
        for k in keys:
            rs = runs[k]
            full = sum(1 for recs in rs.values() if recs[qid]["score"] >= 0.999)
            cells.append(f"{full}/{len(rs)}")
        out.append(f"| {qid} | {TYPE_KO[q['type']]} | " + " | ".join(cells) + " |")

    md = "\n".join(out)
    print(md)
    (HERE / "results" / "summary.md").write_text(md + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
