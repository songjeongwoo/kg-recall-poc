"""NHTSA 리콜 지식그래프 PoC."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ONTOLOGY = ROOT / "ontology" / "recall.ttl"
SHAPES = ROOT / "ontology" / "shapes.ttl"
NS = "https://w3id.org/kg-recall-poc/ontology#"
DATA_NS = "https://w3id.org/kg-recall-poc/data/"
