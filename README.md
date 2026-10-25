# kg-recall-poc — 리콜 데이터로 만든 온톨로지 기반 지식그래프 RAG PoC

미국 NHTSA(National Highway Traffic Safety Administration, 도로교통안전국)의 공개 리콜 데이터 중
Hyundai, Kia, Genesis 리콜 캠페인 408건(2010년 이후)을 온톨로지에 맞춰 지식그래프로 만들고,
여러 단계를 거치는 질문과 집계 질문에서 벡터 RAG와 그래프 질의(SPARQL)를 비교하는 개인 PoC다.

> 상태: 진행 중 (2026-10). 회사 데이터는 쓰지 않는다.

## 구조

```
NHTSA 원본(탭 구분, 행 = 캠페인 x 차종/연식 x 부품)
  │ prepare.py      캠페인 단위로 묶기 (408건)
  ├─ 정형 칸 ─────────────────────────────┐
  │ extract.py      LLM이 결함/결과/조치 문장에서  │
  │                 위험 유형, 조치 유형, 원인 추출 │  (1차 검사: pydantic, 통제 어휘)
  ▼                                        ▼
build_graph.py  ontology/recall.ttl 에 맞춘 RDF 그래프 → ontology/shapes.ttl 로 SHACL 검사
  │                                         (2차 검사: 어긋난 LLM 값은 빼고 보고서에 기록)
  ▼
query.py        SPARQL 질의            mcp_server.py  그래프 질의를 MCP 도구 3개로 제공 (MCP Python SDK 2.x)
eval/           질문 20개 정답셋(완료) → (예정) 벡터 RAG vs LLM이 만든 SPARQL 자동 채점
```

## 온톨로지 (ontology/recall.ttl)

| 클래스 | 뜻 | 주요 관계 |
|---|---|---|
| `RecallCampaign` | 리콜 캠페인(NHTSA 리콜 번호) | `filedBy` → Manufacturer, `affects` → VehicleVariant, `affectsComponent` → Component, `hasHazard` → Hazard, `remedyType` → RemedyType |
| `VehicleVariant` | 연식별 차종 | `ofModel` → VehicleModel, `modelYear` |
| `VehicleModel` / `Make` | 차종 / 브랜드 | `ofMake` → Make |
| `Component` | 부품 분류(`SEATS:FRONT ASSEMBLY:...` 계층) | `skos:broader` → 상위 분류 |
| `Hazard` | 위험 유형 통제 어휘 10개 | 화재, 충돌, 부상, 동력 상실, 제동력 저하 등 |
| `RemedyType` | 조치 유형 통제 어휘 7개 | 교체, 수리, 점검, 소프트웨어 업데이트 등 |

## 실행

```bash
uv venv && uv pip install -e ".[mcp]"
python -m kgpoc.download                 # NHTSA 원본 (~15MB zip)
python -m kgpoc.prepare                  # data/processed/campaigns.jsonl
python -m kgpoc.extract --model haiku    # LLM 추출 (기본: 로컬 Claude Code CLI, --backend anthropic 가능)
python -m kgpoc.build_graph --extracted data/extracted/extractions.jsonl
python -m kgpoc.query queries/03_fire_park_outside.rq
python eval/make_gold.py                 # 평가 질문과 정답
python -m pytest -q tests                # SHACL 규칙 시험
claude mcp add recall-kg -- <저장소>/.venv/Scripts/python.exe -m kgpoc.mcp_server   # MCP 등록
```

## 지금까지 확인한 것

- 정형 칸만으로 트리플 9,685개: 캠페인 408, 연식별 차종 552, 차종 87, 부품 분류 229.
- SHACL 검사가 원본의 예외 형식을 잡아냈다. 리콜 번호 규칙을 `^[0-9]{2}[VEIT][0-9]{6}$`로 두었더니
  `21V00K000`, `21V00M000`처럼 일련번호에 영문자가 들어간 2건이 걸려, 규칙을 원본 형식에 맞게 고쳤다.
- LLM 추출(Claude Haiku, 10건씩 묶음, 약 10분): 408건 모두 pydantic과 SHACL 검사를 통과했다. 추출을 합친 그래프는 트리플 11,364개다.
  위험 유형 분포는 충돌 219, 부상 152, 화재 102, 탑승자 보호 저하 63, 동력 상실 54건 순이다(캠페인 하나에 여러 유형 가능).
- 검증기 자체의 함정도 하나 찾았다. pyshacl은 `inference="none"`이면 `ont_graph`로 넘긴 온톨로지를 데이터에 섞지 않는다.
  그래서 `rc:Injury`가 `rc:Hazard`라는 정의를 보지 못해 정상 추출 408건이 전부 거부됐다. 데이터와 온톨로지를 직접 합쳐 검사하게 고쳤고,
  어휘 밖 값(`Explosion`)과 너무 긴 원인 구절은 계속 거부되는지 `tests/test_shapes.py`로 고정했다.
- 평가 질문 20개(`eval/questions.jsonl`): 조회 4, 조건 검색 3, 여러 단계 5, 집계 8. 정답은 정형 칸으로만 계산해
  그래프 방식이 자기 LLM 추출값으로 채점받는 순환을 막았다.
- `queries/02`: ABS 제어 모듈(`SERVICE BRAKES, HYDRAULIC:ANTILOCK/...:CONTROL UNIT/MODULE`)이
  Hyundai와 Kia 양쪽에 걸친 리콜 캠페인 수가 가장 많은 세부 부품이다. 브랜드를 넘는 공통 결함은
  문서 조각 검색보다 그래프 경로 질의로 바로 나온다.

## 데이터 출처

- NHTSA Datasets and APIs: https://www.nhtsa.gov/node/102181 (Recalls flat file 안내)
- 원본 파일: https://static.nhtsa.gov/odi/ffdd/rcl/FLAT_RCL_POST_2010.zip, 데이터 사전: https://static.nhtsa.gov/odi/ffdd/rcl/RCL.txt
- Data.gov 카탈로그: https://catalog.data.gov/dataset/nhtsas-office-of-defects-investigation-odi-recalls-recalls-flat-file
- 원본 파일은 저장소에 넣지 않는다(`python -m kgpoc.download`로 받음).

## 개발 방식

구현은 Claude Code를 보조 도구로 썼다. 데이터 선정, 온톨로지와 검증 규칙 설계, 평가 설계(정답을 정형 칸으로만 계산해 순환 채점을 막음),
검증기 오류 원인 분석은 직접 판단하고 확인했다. LLM 추출도 Claude Code CLI를 파이프라인 안에서 호출하는 방식으로 했다.
