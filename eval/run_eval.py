"""평가 질문 20개를 세 방식으로 풀고 결과를 저장한다.

- vector : 벡터 검색 상위 k개 캠페인 문서 → LLM 답변
- hybrid : BM25 + 벡터 RRF 상위 k개 → LLM 답변
- graph  : LLM이 온톨로지 설명을 보고 SPARQL 작성 → 그래프 실행(오류·빈 결과면 1회 재시도) → LLM 답변

세 방식 모두 같은 모델, 같은 답변 형식 규칙을 쓴다.

    python eval/run_eval.py --method graph --model sonnet
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from kgpoc.graph_qa import write_sparql
from kgpoc.llm import MODELS, ask_json, usage_get, usage_reset
from kgpoc.vector_index import hybrid_search, search

HERE = Path(__file__).parent
RULES = """Answer format rules (strict):
- Return {"answer": [...]} — always a JSON list of strings. A single answer is a one-item list. Unknown -> [].
- Recall campaign numbers exactly as written, e.g. "23V651000". Dates as YYYY-MM-DD. Years as 4 digits.
- Vehicle model names in upper case without the brand, e.g. "SANTA FE", "G80 ELECTRIFIED".
- Component categories exactly as written in the data, full colon path, e.g. "SEAT BELTS:FRONT".
- Numbers as plain digits without separators.
- For list questions return every item you can support; for 'which one/most' questions return one item."""
ANSWER_SCHEMA = {"type": "object", "properties": {"answer": {"type": "array", "items": {"type": "string"}}},
                 "required": ["answer"], "additionalProperties": False}


def answer_from_context(question: str, context: str, model: str) -> list[str]:
    system = "You answer questions about vehicle recalls using ONLY the provided context.\n" + RULES
    out = ask_json(system, f"Context:\n{context}\n\nQuestion: {question}", ANSWER_SCHEMA, model)
    return out.get("answer", [])


def rag(question: str, model: str, k: int, hybrid: bool) -> dict:
    hits = (hybrid_search if hybrid else search)(question, k)
    ctx = "\n\n---\n\n".join(d for _, d, _ in hits)
    return {"answer": answer_from_context(question, ctx, model), "retrieved": [i for i, _, _ in hits]}


def graph(question: str, model: str) -> dict:
    ga = write_sparql(question, model)  # MCP, A2A 서버와 같은 질의 경로
    ctx = f"SPARQL query:\n{ga.sparql}\n\nResult rows:\n{ga.rows_markdown or '(no rows)'}"
    return {"answer": answer_from_context(question, ctx, model), "sparql_tries": ga.tries}


def graph_direct(question: str, model: str) -> dict:
    """SPARQL 작성 때 답 열(answer_var)까지 지정하게 하고, 답은 그 열 값에서 바로 꺼낸다(LLM 답변 단계 없음)."""
    ga = write_sparql(question, model, with_answer_var=True)
    return {"answer": ga.answer_values, "answer_var": ga.answer_var, "sparql_tries": ga.tries}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--method", choices=["vector", "hybrid", "graph", "graph_direct"], required=True)
    ap.add_argument("--model", default="sonnet", help="haiku | sonnet | opus | fable 또는 모델 ID")
    ap.add_argument("--run", type=int, default=1, help="반복 회차. 결과 파일 이름에 _rN으로 붙는다")
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--only", default=None, help="쉼표로 질문 ID 지정")
    a = ap.parse_args()

    qs = [json.loads(l) for l in (HERE / "questions.jsonl").open(encoding="utf-8")]
    if a.only:
        keep = set(a.only.split(","))
        qs = [q for q in qs if q["id"] in keep]
    out = HERE / "results" / f"{a.method}_{a.model}_r{a.run}.jsonl"
    out.parent.mkdir(exist_ok=True)
    done = {json.loads(l)["id"] for l in out.open(encoding="utf-8")} if out.exists() else set()
    with out.open("a", encoding="utf-8", newline="\n") as f:
        for q in qs:
            if q["id"] in done:
                continue
            t0 = time.time()
            usage_reset()
            try:
                if a.method == "graph":
                    res = graph(q["question"], a.model)
                elif a.method == "graph_direct":
                    res = graph_direct(q["question"], a.model)
                else:
                    res = rag(q["question"], a.model, a.k, a.method == "hybrid")
            except Exception as ex:
                res = {"answer": [], "error": f"{type(ex).__name__}: {ex}"[:500]}
            u = usage_get()
            rec = {"id": q["id"], "method": a.method, "model": a.model, "model_id": MODELS.get(a.model, a.model), "run": a.run,
                   "k": a.k if not a.method.startswith("graph") else None,
                   "seconds": round(time.time() - t0, 1), "llm_calls": u["calls"], "cost_usd": round(u["cost_usd"], 5)} | res
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            f.flush()
            print(f"{q['id']:3} {rec['seconds']:5}s {str(rec['answer'])[:100]}", flush=True)


if __name__ == "__main__":
    main()
