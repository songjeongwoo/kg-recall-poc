"""리콜 지식그래프를 MCP 도구로 제공하는 stdio 서버.

Claude Code 등록 예:
    claude mcp add recall-kg -- C:/DEV/personal/kg-recall-poc/.venv/Scripts/python.exe -m kgpoc.mcp_server

도구
- describe_ontology: 클래스, 관계, 통제 어휘(질의 작성용 스키마 요약)
- sparql_select: 읽기 전용 SELECT/ASK 질의 실행
- find_recalls: 차종, 연식, 위험 유형으로 리콜 찾기(SPARQL을 몰라도 쓰는 고정 질의)
"""
from __future__ import annotations

import re

from mcp.server.mcpserver import MCPServer  # MCP Python SDK 2.x (1.x의 FastMCP)
from rdflib import OWL, RDF, RDFS, Graph

from . import NS, ONTOLOGY
from .query import load_graph, run, to_markdown

mcp = MCPServer("recall-kg", instructions="NHTSA Hyundai/Kia/Genesis recall knowledge graph. Call describe_ontology before writing SPARQL.")
PREFIXES = f"PREFIX rc: <{NS}>\nPREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\nPREFIX skos: <http://www.w3.org/2004/02/skos/core#>\n"
_WRITE = re.compile(r"\b(INSERT|DELETE|LOAD|CLEAR|DROP|CREATE|ADD|MOVE|COPY)\b", re.I)


@mcp.tool()
def describe_ontology() -> str:
    """리콜 온톨로지의 클래스, 관계(도메인→레인지), 위험·조치 유형 통제 어휘를 돌려준다. SPARQL을 쓰기 전에 먼저 호출한다."""
    o = Graph().parse(ONTOLOGY)
    nm = o.namespace_manager
    lines = ["prefix rc: <" + NS + ">", "", "## classes"]
    for c in sorted(o.subjects(RDF.type, OWL.Class)):
        lines.append(f"- {nm.normalizeUri(c)}: {o.value(c, RDFS.comment) or ''}".rstrip(": "))
    lines.append("\n## properties (domain -> range)")
    for kind in (OWL.ObjectProperty, OWL.DatatypeProperty):
        for p in sorted(o.subjects(RDF.type, kind)):
            d, r = o.value(p, RDFS.domain), o.value(p, RDFS.range)
            lines.append(f"- {nm.normalizeUri(p)}: {nm.normalizeUri(d) if d else '*'} -> {nm.normalizeUri(r) if r else '*'}")
    for cls in ("Hazard", "RemedyType"):
        vals = sorted(nm.normalizeUri(s) for s in o.subjects(RDF.type, o.namespace_manager.expand_curie(f"rc:{cls}")))
        lines.append(f"\n## rc:{cls} values\n" + ", ".join(vals))
    lines.append("\n## notes\n- Component names are colon paths like 'SEATS:FRONT ASSEMBLY'; parents via skos:broader.\n"
                 "- Make/model names are upper-case strings in rc:name (e.g. 'KIA', 'TELLURIDE').\n"
                 "- rc:hasHazard, rc:remedyType, rc:rootCause were extracted by an LLM and SHACL-validated.")
    return "\n".join(lines)


@mcp.tool()
def sparql_select(query: str, max_rows: int = 50) -> str:
    """읽기 전용 SPARQL(SELECT 또는 ASK)을 실행하고 Markdown 표로 돌려준다. rc:, rdfs:, skos: 접두어는 자동으로 붙는다."""
    if _WRITE.search(query):
        return "error: read-only. Only SELECT/ASK queries are allowed."
    q = query if "PREFIX rc:" in query else PREFIXES + query
    try:
        if re.search(r"\bASK\b", q, re.I) and not re.search(r"\bSELECT\b", q, re.I):
            return str(bool(load_graph().query(q).askAnswer))
        cols, rows = run(q, limit_rows=max(1, min(max_rows, 200)))
    except Exception as ex:  # 문법 오류는 그대로 돌려줘 모델이 고치게 한다
        return f"error: {type(ex).__name__}: {ex}"
    return to_markdown(cols, rows) + f"\n\n{len(rows)} rows"


@mcp.tool()
def find_recalls(model: str | None = None, year: int | None = None, hazard: str | None = None, limit: int = 20) -> str:
    """차종(예: SANTA FE), 연식(예: 2021), 위험 유형(예: Fire, Crash)으로 리콜 캠페인을 찾는다. 모두 선택 조건이다."""
    f = []
    if model:
        f.append(f'FILTER(CONTAINS(UCASE(?m), "{model.upper().replace(chr(34), "")}"))')
    if year:
        f.append(f'FILTER(STR(?y) = "{int(year)}")')
    if hazard:
        h = re.sub(r"[^A-Za-z]", "", hazard)
        f.append(f"?c rc:hasHazard rc:{h} .")
    q = PREFIXES + f"""
SELECT ?campaign ?date (GROUP_CONCAT(DISTINCT CONCAT(?m, " ", STR(?y)); separator=", ") AS ?vehicles) ?cause
WHERE {{
  ?c rc:campaignNumber ?campaign ; rc:reportReceivedDate ?date ; rc:affects ?v .
  ?v rc:ofModel/rc:name ?m ; rc:modelYear ?y .
  OPTIONAL {{ ?c rc:rootCause ?cause }}
  {' '.join(f)}
}} GROUP BY ?campaign ?date ?cause ORDER BY DESC(?date) LIMIT {max(1, min(limit, 100))}"""
    cols, rows = run(q)
    return to_markdown(cols, rows) + f"\n\n{len(rows)} rows"


if __name__ == "__main__":
    mcp.run()
