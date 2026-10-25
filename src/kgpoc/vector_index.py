"""벡터 RAG 기준선: 캠페인 하나를 문서 하나로 만들고 로컬 임베딩으로 검색한다.

문서에는 그래프에 들어간 정형 칸(리콜 번호, 브랜드, 차종과 연식, 부품, 접수일, 대상 대수, 권고, 주도 기관)과
결함/결과/조치 원문을 모두 넣는다. 두 방식이 같은 정보를 보게 해서, 차이가 정보량이 아니라 접근 방식에서 나오게 한다.

    python -m kgpoc.vector_index        # data/processed/vector_index.npz 생성
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import numpy as np

from . import ROOT

MODEL = "BAAI/bge-small-en-v1.5"
CAMPAIGNS = ROOT / "data" / "processed" / "campaigns.jsonl"
INDEX = ROOT / "data" / "processed" / "vector_index.npz"


def campaign_doc(c: dict) -> str:
    by_model: dict[str, list[int]] = {}
    for v in c["vehicles"]:
        by_model.setdefault(f"{v['make']} {v['model']}", [])
        if v["year"]:
            by_model[f"{v['make']} {v['model']}"].append(v["year"])
    vehicles = "; ".join(f"{k} ({', '.join(map(str, sorted(ys))) or 'year n/a'})" for k, ys in by_model.items())
    d = c["report_received"]
    adv = [n for n, f in (("Do Not Drive", c["do_not_drive"]), ("Park Outside", c["park_outside"])) if f]
    return "\n".join([
        f"Recall campaign {c['campaign']} (manufacturer campaign {c['mfg_campaign'] or 'n/a'}), filed by {c['manufacturer']}.",
        f"Report received: {d[:4]}-{d[4:6]}-{d[6:]}. Influenced by: {c['initiated_by']}. "
        f"Potentially affected units: {c['potentially_affected']}. Consumer advisories: {', '.join(adv) or 'none'}.",
        f"Vehicles: {vehicles}.",
        f"Components: {' | '.join(c['components'])}.",
        f"Defect: {c['defect']}",
        f"Consequence: {c['consequence']}",
        f"Remedy: {c['corrective']}",
    ])


def _embedder():
    from fastembed import TextEmbedding
    return TextEmbedding(MODEL)


def build() -> None:
    camps = [json.loads(l) for l in CAMPAIGNS.open(encoding="utf-8")]
    docs = [campaign_doc(c) for c in camps]
    vecs = np.array(list(_embedder().embed(docs)), dtype=np.float32)
    vecs /= np.linalg.norm(vecs, axis=1, keepdims=True)
    np.savez(INDEX, vecs=vecs, ids=np.array([c["campaign"] for c in camps]), docs=np.array(docs, dtype=object))
    print(f"docs={len(docs)} dim={vecs.shape[1]} -> {INDEX}")


@lru_cache(maxsize=1)
def _load():
    z = np.load(INDEX, allow_pickle=True)
    return z["vecs"], [str(i) for i in z["ids"]], [str(d) for d in z["docs"]], _embedder()


def search(query: str, k: int = 10) -> list[tuple[str, str, float]]:
    vecs, ids, docs, emb = _load()
    q = np.array(list(emb.query_embed([query]))[0], dtype=np.float32)
    q /= np.linalg.norm(q)
    s = vecs @ q
    top = np.argsort(-s)[:k]
    return [(ids[i], docs[i], float(s[i])) for i in top]


@lru_cache(maxsize=1)
def _bm25():
    import re
    from rank_bm25 import BM25Okapi
    _, ids, docs, _ = _load()
    tok = lambda s: re.findall(r"[a-z0-9]+", s.lower())
    return BM25Okapi([tok(d) for d in docs]), tok


def hybrid_search(query: str, k: int = 10, pool: int = 50, rrf_k: int = 60) -> list[tuple[str, str, float]]:
    """BM25(키워드)와 벡터 검색 순위를 RRF로 합친다. 리콜 번호, 차종명 같은 정확한 식별자 검색을 보완한다."""
    vecs, ids, docs, _ = _load()
    bm, tok = _bm25()
    bm_scores = bm.get_scores(tok(query))
    bm_rank = list(np.argsort(-bm_scores)[:pool])
    vec_ids = [ids.index(i) for i, _, _ in search(query, pool)]
    fused: dict[int, float] = {}
    for ranking in (bm_rank, vec_ids):
        for r, idx in enumerate(ranking):
            fused[int(idx)] = fused.get(int(idx), 0.0) + 1.0 / (rrf_k + r + 1)
    top = sorted(fused, key=lambda i: -fused[i])[:k]
    return [(ids[i], docs[i], fused[i]) for i in top]


if __name__ == "__main__":
    build()
