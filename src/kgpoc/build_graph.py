"""캠페인 JSONL(정형 칸)과 LLM 추출 결과를 온톨로지에 맞춘 RDF 그래프로 만들고 SHACL로 검사한다.

    python -m kgpoc.build_graph                       # 정형 칸만
    python -m kgpoc.build_graph --extracted data/extracted/extractions.jsonl

검사에서 걸린 캠페인의 LLM 추출 값은 그래프에서 빼고 보고서에 남긴다(정형 칸은 유지).
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

from pyshacl import validate
from rdflib import RDF, RDFS, XSD, Graph, Literal, Namespace, URIRef
from rdflib.namespace import SKOS

from . import DATA_NS, NS, ONTOLOGY, SHAPES

RC = Namespace(NS)
D = Namespace(DATA_NS)
SH = Namespace("http://www.w3.org/ns/shacl#")


def slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", s.strip()).strip("-").lower() or "unknown"


def ymd(s: str) -> Literal | None:
    if re.fullmatch(r"\d{8}", s or ""):
        return Literal(f"{s[:4]}-{s[4:6]}-{s[6:]}", datatype=XSD.date)
    return None


def add_component(g: Graph, path: str) -> URIRef:
    """'SEATS:FRONT ASSEMBLY:POWER ADJUST' -> 세 단계 노드와 skos:broader."""
    parts = [p.strip() for p in path.split(":") if p.strip()]
    parent = None
    node = None
    for i in range(len(parts)):
        full = ":".join(parts[: i + 1])
        node = D["component/" + slug(full)]
        g.add((node, RDF.type, RC.Component))
        g.add((node, RC.name, Literal(full)))
        g.add((node, RDFS.label, Literal(parts[i])))
        if parent is not None:
            g.add((node, SKOS.broader, parent))
        parent = node
    return node


def campaign_triples(g: Graph, c: dict) -> URIRef:
    cu = D["campaign/" + c["campaign"]]
    g.add((cu, RDF.type, RC.RecallCampaign))
    # 타입 없는 문자열로 넣는다. RDF 1.1에서는 xsd:string과 같지만 rdflib는 둘을 다른 값으로 비교한다.
    g.add((cu, RC.campaignNumber, Literal(c["campaign"])))
    if c["mfg_campaign"]:
        g.add((cu, RC.manufacturerCampaignNumber, Literal(c["mfg_campaign"])))
    mu = D["manufacturer/" + slug(c["manufacturer"])]
    g.add((mu, RDF.type, RC.Manufacturer))
    g.add((mu, RC.name, Literal(c["manufacturer"])))
    g.add((cu, RC.filedBy, mu))
    if (dt := ymd(c["report_received"])) is not None:
        g.add((cu, RC.reportReceivedDate, dt))
    if c["potentially_affected"] is not None:
        g.add((cu, RC.potentiallyAffected, Literal(c["potentially_affected"], datatype=XSD.integer)))
    if c["initiated_by"]:
        g.add((cu, RC.initiatedBy, Literal(c["initiated_by"])))
    for key, prop in (("do_not_drive", RC.doNotDrive), ("park_outside", RC.parkOutside)):
        if c[key] is not None:
            g.add((cu, prop, Literal(c[key], datatype=XSD.boolean)))
    for key, prop in (("defect", RC.defectSummary), ("consequence", RC.consequenceSummary),
                      ("corrective", RC.correctiveSummary)):
        if c[key]:
            g.add((cu, prop, Literal(c[key])))
    for v in c["vehicles"]:
        mk = D["make/" + slug(v["make"])]
        g.add((mk, RDF.type, RC.Make))
        g.add((mk, RC.name, Literal(v["make"])))
        mo = D["model/" + slug(v["make"] + "-" + v["model"])]
        g.add((mo, RDF.type, RC.VehicleModel))
        g.add((mo, RC.name, Literal(v["model"])))
        g.add((mo, RC.ofMake, mk))
        if v["year"] is None:
            continue  # 연식 미상(9999)은 차종 노드만 둔다
        vv = D[f"variant/{slug(v['make'] + '-' + v['model'])}-{v['year']}"]
        g.add((vv, RDF.type, RC.VehicleVariant))
        g.add((vv, RC.ofModel, mo))
        g.add((vv, RC.modelYear, Literal(str(v["year"]), datatype=XSD.gYear)))
        g.add((cu, RC.affects, vv))
    for comp in c["components"]:
        g.add((cu, RC.affectsComponent, add_component(g, comp)))
    return cu


def extraction_triples(g: Graph, cu: URIRef, e: dict) -> None:
    for h in e.get("hazards", []):
        g.add((cu, RC.hasHazard, RC[h]))
    for r in e.get("remedy_types", []):
        g.add((cu, RC.remedyType, RC[r]))
    if e.get("root_cause"):
        g.add((cu, RC.rootCause, Literal(e["root_cause"])))


def shacl(g: Graph) -> tuple[bool, Graph, str]:
    ont = Graph().parse(ONTOLOGY)
    shapes = Graph().parse(SHAPES)
    # pyshacl은 inference="none"이면 ont_graph를 데이터에 섞지 않는다. 통제 어휘의 rdf:type을 보려면 직접 합친다.
    conforms, report_g, report_t = validate(g + ont, shacl_graph=shapes, inference="none",
                                            allow_warnings=True)
    return conforms, report_g, report_t


def focus_nodes(report_g: Graph) -> set[URIRef]:
    return {o for o in report_g.objects(None, SH.focusNode)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--campaigns", type=Path, default=Path("data/processed/campaigns.jsonl"))
    ap.add_argument("--extracted", type=Path, default=None)
    ap.add_argument("--out", type=Path, default=Path("data/graph.ttl"))
    ap.add_argument("--report", type=Path, default=Path("data/shacl_report.txt"))
    a = ap.parse_args()

    camps = [json.loads(l) for l in a.campaigns.open(encoding="utf-8")]
    ext = {}
    if a.extracted and a.extracted.exists():
        for l in a.extracted.open(encoding="utf-8"):
            if l.strip():
                e = json.loads(l)
                ext[e["campaign"]] = e

    g = Graph()
    g.bind("rc", RC); g.bind("d", D); g.bind("skos", SKOS)
    uris = {c["campaign"]: campaign_triples(g, c) for c in camps}
    for cid, e in ext.items():
        if cid in uris:
            extraction_triples(g, uris[cid], e)

    conforms, report_g, report_t = shacl(g)
    dropped = []
    if not conforms:
        # LLM 추출 값 때문에 걸린 캠페인은 추출 값을 빼고 다시 검사
        bad = focus_nodes(report_g)
        for cid, cu in uris.items():
            if cu in bad and cid in ext:
                for p in (RC.hasHazard, RC.remedyType, RC.rootCause):
                    g.remove((cu, p, None))
                dropped.append(cid)
        if dropped:
            conforms, report_g, report_t = shacl(g)

    a.out.parent.mkdir(parents=True, exist_ok=True)
    g.serialize(a.out, format="turtle")
    a.report.write_text(report_t, encoding="utf-8")

    types = Counter(o for o in g.objects(None, RDF.type))
    print(f"triples={len(g)} conforms={conforms} llm_dropped={len(dropped)} extracted={len(ext)}")
    for t, n in types.most_common():
        print(f"  {g.namespace_manager.normalizeUri(t)}: {n}")
    print(f"-> {a.out}, report -> {a.report}")


if __name__ == "__main__":
    main()
