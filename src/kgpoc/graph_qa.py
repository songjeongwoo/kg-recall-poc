"""자연어 질문 → LLM이 SPARQL 작성 → 그래프 실행(오류·빈 결과면 1회 재시도) → 근거 표와 함께 답변.

MCP 서버, A2A 서버, 평가 스크립트가 같은 질의 경로를 쓰도록 여기 한 곳에 둔다.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .llm import ask_json
from .mcp_server import PREFIXES, describe_ontology
from .query import run, to_markdown

SPARQL_SCHEMA = {"type": "object", "properties": {"sparql": {"type": "string"}},
                 "required": ["sparql"], "additionalProperties": False}
ANSWER_SCHEMA = {"type": "object", "properties": {"answer": {"type": "string"}},
                 "required": ["answer"], "additionalProperties": False}
# 답이 들어 있는 SELECT 변수까지 지정하게 하면, 결과 행을 다시 LLM에 읽히지 않고 그 열에서 바로 답을 꺼낼 수 있다.
SPARQL_VAR_SCHEMA = {"type": "object",
                     "properties": {"sparql": {"type": "string"}, "answer_var": {"type": "string"}},
                     "required": ["sparql", "answer_var"], "additionalProperties": False}
ANSWER_VAR_RULES = ("\nAlso return answer_var: the SELECT variable name (without '?') whose values directly answer the question. "
                    "That variable must hold human-readable values (rc:name strings, campaign numbers, dates, numbers), "
                    "not URIs. Order rows so that for 'which one/most' questions the answer is in the first row.")


@dataclass
class GraphAnswer:
    question: str
    sparql: str = ""
    rows_markdown: str = ""
    row_count: int = 0
    answer: str = ""
    answer_var: str | None = None
    answer_values: list[str] = field(default_factory=list)
    tries: list[dict] = field(default_factory=list)

    @property
    def found(self) -> bool:
        return self.row_count > 0


def write_sparql(question: str, model: str = "sonnet", max_tries: int = 2, with_answer_var: bool = False) -> GraphAnswer:
    system = ("You translate questions into SPARQL 1.1 SELECT queries over an RDF knowledge graph of vehicle recalls.\n"
              "The prefixes rc:, rdfs:, skos: are predeclared; do not repeat them. Return {\"sparql\": \"...\"}.\n"
              + (ANSWER_VAR_RULES if with_answer_var else "") + "\n\n" + describe_ontology())
    schema = SPARQL_VAR_SCHEMA if with_answer_var else SPARQL_SCHEMA
    ga = GraphAnswer(question)
    prompt = f"Question: {question}"
    for _ in range(max_tries):
        out = ask_json(system, prompt, schema, model)
        q, var = out["sparql"], (out.get("answer_var") or "").lstrip("?") or None
        try:
            cols, rows = run(PREFIXES + q, limit_rows=300)
            err = None if rows else "query returned 0 rows"
            if not err and with_answer_var and var not in cols:
                err = f"answer_var '{var}' is not a SELECT variable; columns are {cols}"
        except Exception as ex:
            cols, rows, err = [], [], f"{type(ex).__name__}: {ex}"
        ga.tries.append({"sparql": q, "answer_var": var, "rows": len(rows), "error": err})
        ga.sparql, ga.answer_var = q, var
        if not err:
            ga.rows_markdown, ga.row_count = to_markdown(cols, rows), len(rows)
            if with_answer_var:
                i = cols.index(var)
                ga.answer_values = list(dict.fromkeys(r[i] for r in rows if r[i]))
            break
        prompt = (f"Question: {question}\n\nYour previous query:\n{q}\n\nProblem: {err}\n"
                  "Fix the query (check literal spellings, upper case names, property paths).")
    return ga


def answer(question: str, model: str = "sonnet") -> GraphAnswer:
    ga = write_sparql(question, model)
    if ga.found:
        system = ("Answer the user's question about vehicle recalls using ONLY the SPARQL result rows. "
                  "Be concise. Cite recall campaign numbers when relevant. Answer in the user's language.")
        ga.answer = ask_json(system, f"Question: {question}\n\nSPARQL:\n{ga.sparql}\n\nRows:\n{ga.rows_markdown}",
                             ANSWER_SCHEMA, model)["answer"]
    return ga
