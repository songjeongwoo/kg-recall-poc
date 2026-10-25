"""SHACL 규칙이 통제 어휘 밖의 LLM 값을 거르는지 확인한다.  python -m pytest -q"""
import json

from rdflib import Graph, Literal

from kgpoc import build_graph as b

CAMP = {"campaign": "26V430000", "mfg_campaign": "SC374", "manufacturer": "Kia America, Inc.", "type": "V",
        "initiated_by": "MFR", "report_received": "20260702", "owner_notified": "", "fmvss": "",
        "potentially_affected": 462869, "do_not_drive": False, "park_outside": True,
        "defect": "d", "consequence": "c", "corrective": "r", "notes": "",
        "vehicles": [{"make": "KIA", "model": "TELLURIDE", "year": 2024}],
        "components": ["SEATS:FRONT ASSEMBLY:POWER ADJUST"], "parts": []}


def _graph(ext):
    g = Graph()
    cu = b.campaign_triples(g, json.loads(json.dumps(CAMP)))
    b.extraction_triples(g, cu, ext)
    return g


def test_valid_extraction_conforms():
    ok, _, report = b.shacl(_graph({"hazards": ["Fire"], "remedy_types": ["Replace"], "root_cause": "seat motor overheats"}))
    assert ok, report


def test_unknown_hazard_is_rejected():
    ok, _, _ = b.shacl(_graph({"hazards": ["Explosion"], "remedy_types": ["Replace"], "root_cause": "x" * 10}))
    assert not ok


def test_too_long_root_cause_is_rejected():
    ok, _, _ = b.shacl(_graph({"hazards": ["Fire"], "remedy_types": ["Replace"], "root_cause": "x" * 300}))
    assert not ok
