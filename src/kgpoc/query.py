"""그래프(+온톨로지)에 SPARQL을 실행해 표로 출력한다.

    python -m kgpoc.query queries/01_component_spread.rq
    python -m kgpoc.query --sparql "SELECT (COUNT(*) AS ?n) WHERE { ?s ?p ?o }"
"""
from __future__ import annotations

import argparse
from functools import lru_cache
from pathlib import Path

from rdflib import Graph

from . import ONTOLOGY, ROOT

GRAPH = ROOT / "data" / "graph.ttl"


@lru_cache(maxsize=1)
def load_graph(path: str = str(GRAPH)) -> Graph:
    g = Graph()
    g.parse(path)
    g.parse(ONTOLOGY)  # 위험·조치 유형의 라벨을 질의에 쓰기 위해 함께 올림
    return g


def run(sparql: str, limit_rows: int = 200) -> tuple[list[str], list[list[str]]]:
    res = load_graph().query(sparql)
    cols = [str(v) for v in res.vars]
    rows = [["" if v is None else str(v) for v in r] for r in list(res)[:limit_rows]]
    return cols, rows


def to_markdown(cols: list[str], rows: list[list[str]]) -> str:
    out = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    out += ["| " + " | ".join(c.replace("|", "/")[:120] for c in r) + " |" for r in rows]
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("file", nargs="?", type=Path)
    ap.add_argument("--sparql")
    a = ap.parse_args()
    q = a.sparql or a.file.read_text(encoding="utf-8")
    cols, rows = run(q)
    print(to_markdown(cols, rows))
    print(f"\n{len(rows)} rows")


if __name__ == "__main__":
    main()
