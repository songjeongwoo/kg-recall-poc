"""평가 질문 20개와 정답을 만든다. 정답은 원본 정형 칸에서 나온 트리플로만 계산한다.

LLM 추출 값(rc:hasHazard, rc:remedyType, rc:rootCause)은 정답 계산에 쓰지 않는다.
그래프 방식이 자기 추출 결과로 채점받는 순환을 막기 위해서다.

    python eval/make_gold.py   -> eval/questions.jsonl
"""
from __future__ import annotations

import json
from pathlib import Path

from kgpoc.query import run

P = """PREFIX rc: <https://w3id.org/kg-recall-poc/ontology#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
"""
ABS = "SERVICE BRAKES, HYDRAULIC:ANTILOCK/TRACTION CONTROL/ELECTRONIC LIMITED SLIP:CONTROL UNIT/MODULE"
TOP = "?comp skos:broader* ?t . FILTER NOT EXISTS { ?t skos:broader ?x } ?t rc:name ?top ."

# (id, 유형, 채점 방식, 영어 질문, 한국어 질문, 정답 SPARQL)
# 채점: set = 정답 집합과 F1, exact = 첫 행 첫 칸 일치, number = 첫 행 첫 칸 수치 일치
Q = [
    ("L1", "lookup", "set", "Which model years of the Kia Telluride are covered by recall 26V430000?",
     "리콜 26V430000의 대상 텔루라이드 연식은?",
     'SELECT DISTINCT ?y WHERE { ?c rc:campaignNumber "26V430000" ; rc:affects ?v . ?v rc:modelYear ?y }'),
    ("L2", "lookup", "set", "Which component categories are recalled in campaign 10V388000?",
     "리콜 10V388000의 결함 부품 분류는?",
     'SELECT DISTINCT ?n WHERE { ?c rc:campaignNumber "10V388000" ; rc:affectsComponent ?k . ?k rc:name ?n }'),
    ("L3", "lookup", "exact", "On what date did NHTSA receive the defect report for recall 23V651000?",
     "리콜 23V651000의 결함 보고 접수일은?",
     'SELECT ?d WHERE { ?c rc:campaignNumber "23V651000" ; rc:reportReceivedDate ?d }'),
    ("L4", "lookup", "number", "How many vehicles are potentially affected by recall 26V430000?",
     "리콜 26V430000의 잠재 대상 대수는?",
     'SELECT ?n WHERE { ?c rc:campaignNumber "26V430000" ; rc:potentiallyAffected ?n }'),
    ("F1", "filter", "set", "List every Hyundai, Kia or Genesis recall campaign that carries a 'Do Not Drive' advisory.",
     "'운전 금지' 권고가 붙은 리콜 캠페인을 모두 나열하라.",
     "SELECT ?cn WHERE { ?c rc:doNotDrive true ; rc:campaignNumber ?cn }"),
    ("F2", "filter", "set", "Which of these recalls were influenced by NHTSA's OVSC (Office of Vehicle Safety Compliance)?",
     "OVSC(차량안전기준 준수국) 주도로 시작된 리콜은?",
     'SELECT ?cn WHERE { ?c rc:initiatedBy "OVSC" ; rc:campaignNumber ?cn }'),
    ("F3", "filter", "set", "Which recall campaigns received in 2024 affect the Hyundai Palisade?",
     "2024년에 접수된 리콜 중 팰리세이드가 대상인 캠페인은?",
     'SELECT DISTINCT ?cn WHERE { ?c rc:campaignNumber ?cn ; rc:reportReceivedDate ?d ; rc:affects/rc:ofModel/rc:name "PALISADE" . FILTER(YEAR(?d) = 2024) }'),
    ("M1", "multi-hop", "set", f"Which vehicle models, across all three brands, have been recalled for the component '{ABS}'?",
     "ABS 제어 모듈 결함으로 리콜된 차종을 브랜드 구분 없이 모두 나열하라.",
     f'SELECT DISTINCT ?m WHERE {{ ?c rc:affectsComponent/rc:name "{ABS}" ; rc:affects/rc:ofModel/rc:name ?m }}'),
    ("M2", "multi-hop", "exact", "Among detailed component categories that appear in both Hyundai and Kia recalls, which one appears in the most campaigns?",
     "Hyundai와 Kia 리콜에 모두 나온 세부 부품 분류 중 캠페인 수가 가장 많은 것은?",
     """SELECT ?n (COUNT(DISTINCT ?c) AS ?k) WHERE {
          ?a rc:affectsComponent ?comp ; rc:affects/rc:ofModel/rc:ofMake/rc:name "HYUNDAI" .
          ?b rc:affectsComponent ?comp ; rc:affects/rc:ofModel/rc:ofMake/rc:name "KIA" .
          ?c rc:affectsComponent ?comp . ?comp rc:name ?n . FILTER(CONTAINS(?n, ":")) }
        GROUP BY ?n ORDER BY DESC(?k) LIMIT 1"""),
    ("M3", "multi-hop", "set", "Which single recall campaigns cover vehicles of more than one brand (Hyundai, Kia, Genesis)?",
     "한 캠페인에 두 개 이상 브랜드의 차량이 함께 들어간 리콜은?",
     """SELECT ?cn WHERE { ?c rc:campaignNumber ?cn ; rc:affects/rc:ofModel/rc:ofMake ?mk }
        GROUP BY ?cn HAVING (COUNT(DISTINCT ?mk) > 1)"""),
    ("M4", "multi-hop", "set", "List every recall campaign that covers the 2021 model-year Hyundai Santa Fe.",
     "2021년식 싼타페가 대상인 리콜 캠페인을 모두 나열하라.",
     """SELECT DISTINCT ?cn WHERE { ?c rc:campaignNumber ?cn ; rc:affects ?v .
          ?v rc:modelYear ?y ; rc:ofModel/rc:name "SANTA FE" . FILTER(STR(?y) = "2021") }"""),
    ("M5", "multi-hop", "set", "Which Genesis models were recalled for a detailed component category that was also recalled on the Kia Telluride?",
     "텔루라이드 리콜과 같은 세부 부품 분류로 리콜된 Genesis 차종은?",
     """SELECT DISTINCT ?m WHERE {
          ?t rc:affects/rc:ofModel/rc:name "TELLURIDE" ; rc:affectsComponent ?comp .
          ?g rc:affectsComponent ?comp ; rc:affects/rc:ofModel ?mo . ?mo rc:ofMake/rc:name "GENESIS" ; rc:name ?m .
          ?comp rc:name ?n . FILTER(CONTAINS(?n, ":")) }"""),
    ("A1", "aggregate", "exact", "Which vehicle model has the most recall campaigns in this dataset?",
     "리콜 캠페인이 가장 많은 차종은?",
     "SELECT ?m (COUNT(DISTINCT ?c) AS ?n) WHERE { ?c rc:affects/rc:ofModel/rc:name ?m } GROUP BY ?m ORDER BY DESC(?n) LIMIT 1"),
    ("A2", "aggregate", "number", "How many Hyundai, Kia or Genesis recall campaigns were received in 2023?",
     "2023년에 접수된 리콜 캠페인 수는?",
     "SELECT (COUNT(DISTINCT ?c) AS ?n) WHERE { ?c rc:reportReceivedDate ?d . FILTER(YEAR(?d) = 2023) }"),
    ("A3", "aggregate", "exact", "Which top-level component category has recalls affecting the largest number of distinct vehicle models?",
     "가장 많은 차종에 걸쳐 리콜된 최상위 부품 분류는?",
     f"SELECT ?top (COUNT(DISTINCT ?m) AS ?n) WHERE {{ ?c rc:affectsComponent ?comp ; rc:affects/rc:ofModel ?m . {TOP} }} GROUP BY ?top ORDER BY DESC(?n) LIMIT 1"),
    ("A4", "aggregate", "exact", "Among campaigns with a 'Park Outside' advisory, which one has the most potentially affected vehicles?",
     "'실외 주차' 권고 리콜 중 잠재 대상 대수가 가장 많은 캠페인은?",
     "SELECT ?cn ?n WHERE { ?c rc:parkOutside true ; rc:campaignNumber ?cn ; rc:potentiallyAffected ?n } ORDER BY DESC(?n) LIMIT 1"),
    ("A5", "aggregate", "number", "How many of these recall campaigns were influenced by NHTSA's ODI (Office of Defects Investigation)?",
     "ODI(결함조사국) 주도로 시작된 리콜 캠페인 수는?",
     'SELECT (COUNT(?c) AS ?n) WHERE { ?c rc:initiatedBy "ODI" }'),
    ("A6", "aggregate", "exact", "In recalls of Genesis vehicles, which top-level component category appears in the most campaigns?",
     "Genesis 리콜에서 캠페인 수가 가장 많은 최상위 부품 분류는?",
     f'SELECT ?top (COUNT(DISTINCT ?c) AS ?n) WHERE {{ ?c rc:affectsComponent ?comp ; rc:affects/rc:ofModel/rc:ofMake/rc:name "GENESIS" . {TOP} }} GROUP BY ?top ORDER BY DESC(?n) LIMIT 1'),
    ("A7", "aggregate", "number", "How many distinct model years of the Hyundai Sonata have at least one recall in this dataset?",
     "리콜이 한 건 이상 있는 쏘나타 연식은 몇 개인가?",
     'SELECT (COUNT(DISTINCT ?y) AS ?n) WHERE { ?c rc:affects ?v . ?v rc:ofModel/rc:name "SONATA" ; rc:modelYear ?y }'),
    ("A8", "aggregate", "exact", "In which year did NHTSA receive the most Hyundai, Kia or Genesis recall reports?",
     "리콜 보고가 가장 많이 접수된 연도는?",
     "SELECT ?y (COUNT(DISTINCT ?c) AS ?n) WHERE { ?c rc:reportReceivedDate ?d . BIND(YEAR(?d) AS ?y) } GROUP BY ?y ORDER BY DESC(?n) LIMIT 1"),
]


# 문장 이해 질문: 정답은 그래프가 아니라 원문 결함/결과 문장의 정규식 일치로 계산한다(그래프와 독립).
# 질문은 키워드를 그대로 쓰지 않고 풀어서 묻는다.
# T3 규칙은 1차 채점 뒤 세 방식이 공통으로 답한 11E040000, 11E041000을 원문 확인한 결과 "tow package wiring harness"
# 표현을 놓친 것이라 (hitch|package)로 고쳤다(2026-10-25). 고친 규칙은 세 방식에 똑같이 적용된다.
TEXT_Q = [
    ("T1", "Which recalls concern leaks of the hydrogen fuel used by fuel-cell vehicles, or failure to detect such leaks?",
     "수소연료전지차의 수소 누출(또는 누출 감지 실패)과 관련된 리콜은?", r"hydrogen"),
    ("T2", "Which recalls concern the unit that charges the 12-volt battery in electrified vehicles (the integrated charging control unit)?",
     "전동화 차량에서 12V 배터리를 충전하는 통합 충전 제어 장치(ICCU) 관련 리콜은?",
     r"\bICCU\b|Integrated Charging Control Unit"),
    ("T3", "Which recalls are about water or moisture getting into an electronic module through towing (trailer hitch) wiring?",
     "견인(트레일러 히치) 배선을 통해 물이나 습기가 전자 모듈로 들어가는 문제의 리콜은?",
     r"(tow|trailer) (hitch|package).*(water|moisture)|(water|moisture).*(tow|trailer) (hitch|package)"),
    ("T4", "Which recalls describe premature wear of the engine's connecting rod bearings?",
     "엔진 커넥팅 로드 베어링의 조기 마모를 다룬 리콜은?", r"connecting rod bearing"),
]


def text_gold(pattern: str) -> list[str]:
    import re
    camps = [json.loads(l) for l in (Path(__file__).parents[1] / "data/processed/campaigns.jsonl").open(encoding="utf-8")]
    r = re.compile(pattern, re.I)
    return sorted(c["campaign"] for c in camps if r.search(c["defect"] + " " + c["consequence"]))


def main() -> None:
    out = Path(__file__).with_name("questions.jsonl")
    with out.open("w", encoding="utf-8", newline="\n") as f:
        for qid, kind, grade, en, ko, sparql in Q:
            cols, rows = run(P + sparql, limit_rows=500)
            if grade == "set":
                gold = sorted({r[0] for r in rows})
            else:
                gold = rows[0][0] if rows else None
            rec = {"id": qid, "type": kind, "grading": grade, "question": en, "question_ko": ko,
                   "gold": gold, "gold_sparql": sparql.strip()}
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            shown = gold if not isinstance(gold, list) else f"{len(gold)} items: {gold[:6]}"
            print(f"{qid:3} {kind:9} {shown}")
        for qid, en, ko, pattern in TEXT_Q:
            gold = text_gold(pattern)
            rec = {"id": qid, "type": "text", "grading": "set", "question": en, "question_ko": ko,
                   "gold": gold, "gold_rule": f"regex on defect+consequence text: {pattern}"}
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            print(f"{qid:3} text      {len(gold)} items: {gold}")
    print(f"-> {out}")


if __name__ == "__main__":
    main()
