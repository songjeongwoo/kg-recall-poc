"""README용 그래프 그림을 만든다. data/graph.ttl이 있어야 한다(python -m kgpoc.build_graph).

    python scripts/visualize.py      # docs/graph_overview_{light,dark}.png, docs/graph_abs_{light,dark}.png

색: 노드 유형 3개(캠페인, 차종, 부품)만 색으로 구분한다. 산점도처럼 모든 쌍이 맞닿는 그림이라
색약 검사를 모든 쌍 기준으로 통과하는 세 색까지만 쓰고, 나머지(브랜드)는 무채색과 글자로 표시한다.
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import networkx as nx  # noqa: E402

from kgpoc import ROOT  # noqa: E402
from kgpoc.query import run  # noqa: E402

OUT = ROOT / "docs"
P = "PREFIX rc: <https://w3id.org/kg-recall-poc/ontology#>\nPREFIX skos: <http://www.w3.org/2004/02/skos/core#>\n"
ABS = "SERVICE BRAKES, HYDRAULIC:ANTILOCK/TRACTION CONTROL/ELECTRONIC LIMITED SLIP:CONTROL UNIT/MODULE"

# 검증한 팔레트(밝은/어두운 면 각각): 1 blue, 2 orange, 3 aqua. validate_palette.js --pairs all 통과.
THEMES = {
    "light": {"surface": "#fcfcfb", "ink": "#0b0b0b", "ink2": "#52514e", "muted": "#898781", "edge": "#c3c2b7",
              "campaign": "#2a78d6", "model": "#eb6834", "component": "#1baf7a", "ring": "#fcfcfb"},
    "dark": {"surface": "#1a1a19", "ink": "#f0efec", "ink2": "#c3c2b7", "muted": "#898781", "edge": "#383835",
             "campaign": "#3987e5", "model": "#d95926", "component": "#199e70", "ring": "#1a1a19"},
}
LABEL = {"campaign": "리콜 캠페인", "model": "차종", "component": "부품 분류"}
plt.rcParams["font.family"] = ["Malgun Gothic", "AppleGothic", "NanumGothic", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False


def heading(ax, t: dict, title: str, sub: str) -> None:
    ax.text(0, 1.055, title, transform=ax.transAxes, fontsize=14, color=t["ink"], va="bottom", ha="left")
    ax.text(0, 1.02, sub, transform=ax.transAxes, fontsize=9.5, color=t["ink2"], va="bottom", ha="left")


def component_label(path: str) -> str:
    """'SEAT BELTS:FRONT' -> 'Seat Belts: Front'. 끝 두 단계만 보여 무슨 부품인지 알 수 있게 한다."""
    parts = [p.strip().title() for p in path.split(":")]
    return ": ".join(parts[-2:]).replace("Antilock/Traction Control/Electronic Limited Slip", "ABS")


def build_overview() -> nx.Graph:
    g = nx.Graph()
    _, rows = run(P + "SELECT DISTINCT ?cn ?m WHERE { ?c rc:campaignNumber ?cn ; rc:affects/rc:ofModel/rc:name ?m }", 100000)
    for cn, m in rows:
        g.add_node(("c", cn), kind="campaign"); g.add_node(("m", m), kind="model"); g.add_edge(("c", cn), ("m", m))
    _, rows = run(P + "SELECT DISTINCT ?cn ?k WHERE { ?c rc:campaignNumber ?cn ; rc:affectsComponent/rc:name ?k }", 100000)
    for cn, k in rows:
        g.add_node(("c", cn), kind="campaign"); g.add_node(("k", k), kind="component"); g.add_edge(("c", cn), ("k", k))
    _, rows = run(P + "SELECT DISTINCT ?a ?b WHERE { ?x rc:name ?a ; skos:broader/rc:name ?b }", 100000)
    for a, b in rows:
        if ("k", a) in g:
            g.add_node(("k", b), kind="component"); g.add_edge(("k", a), ("k", b))
    return g


def draw_overview(g: nx.Graph, theme: str) -> Path:
    t = THEMES[theme]
    pos = nx.forceatlas2_layout(g, max_iter=400, scaling_ratio=2.0, gravity=1.0, seed=7)
    fig, ax = plt.subplots(figsize=(12, 9), dpi=150)
    fig.patch.set_facecolor(t["surface"]); ax.set_facecolor(t["surface"]); ax.axis("off")
    nx.draw_networkx_edges(g, pos, ax=ax, edge_color=t["edge"], width=0.35, alpha=0.6)
    deg = dict(g.degree())
    counts = Counter(d["kind"] for _, d in g.nodes(data=True))
    for kind in ("component", "model", "campaign"):
        nodes = [n for n, d in g.nodes(data=True) if d["kind"] == kind]
        sizes = [8 + 3.2 * math.sqrt(deg[n]) ** 2 if kind != "campaign" else 9 for n in nodes]
        nx.draw_networkx_nodes(g, pos, nodelist=nodes, node_size=sizes, node_color=t[kind], ax=ax,
                               edgecolors=t["ring"], linewidths=0.6, label=f"{LABEL[kind]} {counts[kind]}")
    # 연결이 많은 차종과 부품만 이름을 붙인다(선택적 직접 라벨)
    hubs = sorted((n for n in g if n[0] in ("m", "k")), key=lambda n: -deg[n])[:12]
    for n in hubs:
        x, y = pos[n]
        name = component_label(n[1]) if n[0] == "k" else n[1].title()
        ax.annotate(name, (x, y), xytext=(4, 4), textcoords="offset points", fontsize=8.5, color=t["ink"],
                    bbox=dict(boxstyle="round,pad=0.15", fc=t["surface"], ec="none", alpha=0.75))
    leg = ax.legend(loc="lower left", frameon=False, fontsize=10, labelcolor=t["ink2"], markerscale=1.6)
    for h in leg.legend_handles:
        h.set_sizes([60])
    heading(ax, t, "Hyundai, Kia, Genesis 리콜 지식그래프 (NHTSA, 2010년 이후 408건)",
            "점 크기 = 연결된 리콜 수. 차종은 연식을 합쳐 한 점으로, 부품은 상위 분류까지 이어서 그렸다.")
    OUT.mkdir(exist_ok=True)
    path = OUT / f"graph_overview_{theme}.png"
    fig.savefig(path, facecolor=t["surface"], bbox_inches="tight")
    plt.close(fig)
    return path


def draw_abs(theme: str) -> Path:
    """ABS 제어 모듈 하나에서 리콜 캠페인 → 차종으로 퍼지는 부분 그래프(브랜드별 정렬)."""
    t = THEMES[theme]
    _, rows = run(P + f'''SELECT DISTINCT ?cn ?make ?m WHERE {{
        ?c rc:affectsComponent/rc:name "{ABS}" ; rc:campaignNumber ?cn ; rc:affects/rc:ofModel ?mo .
        ?mo rc:name ?m ; rc:ofMake/rc:name ?make }}''', 10000)
    camp_models = defaultdict(set); model_make = {}; camp_make = defaultdict(Counter)
    for cn, make, m in rows:
        camp_models[cn].add(m); model_make[m] = make; camp_make[cn][make] += 1
    order = {"HYUNDAI": 0, "GENESIS": 1, "KIA": 2}
    models = sorted(model_make, key=lambda m: (order.get(model_make[m], 9), m))
    camps = sorted(camp_models, key=lambda c: (order.get(camp_make[c].most_common(1)[0][0], 9), c))

    fig, ax = plt.subplots(figsize=(11, 11), dpi=150)
    fig.patch.set_facecolor(t["surface"]); ax.set_facecolor(t["surface"]); ax.axis("off"); ax.set_aspect("equal")
    pos = {("k", "ABS"): (0.0, 0.0)}
    for i, c in enumerate(camps):  # 안쪽 원: 캠페인
        a = math.pi / 2 - 2 * math.pi * (i + 0.5) / len(camps)
        pos[("c", c)] = (0.42 * math.cos(a), 0.42 * math.sin(a))
    for i, m in enumerate(models):  # 바깥 원: 차종
        a = math.pi / 2 - 2 * math.pi * (i + 0.5) / len(models)
        pos[("m", m)] = (1.0 * math.cos(a), 1.0 * math.sin(a))
    for c in camps:
        ax.plot(*zip(pos[("k", "ABS")], pos[("c", c)]), color=t["edge"], lw=0.9, zorder=1)
        for m in camp_models[c]:
            ax.plot(*zip(pos[("c", c)], pos[("m", m)]), color=t["edge"], lw=0.6, zorder=1, alpha=0.9)
    ax.scatter(*zip(*[pos[("m", m)] for m in models]), s=70, c=t["model"], edgecolors=t["ring"], linewidths=1.2, zorder=3,
               label=f"차종 {len(models)}")
    ax.scatter(*zip(*[pos[("c", c)] for c in camps]), s=90, c=t["campaign"], edgecolors=t["ring"], linewidths=1.2, zorder=3,
               label=f"리콜 캠페인 {len(camps)}")
    ax.scatter([0], [0], s=420, c=t["component"], edgecolors=t["ring"], linewidths=1.5, zorder=4, label="부품 분류 1")
    ax.annotate("ABS 제어 모듈", (0, 0), xytext=(0, -22), textcoords="offset points", ha="center", fontsize=10.5,
                color=t["ink"], fontweight="bold")
    for m in models:
        x, y = pos[("m", m)]; ang = math.degrees(math.atan2(y, x))
        rot = ang if -90 <= ang <= 90 else ang + 180
        ax.text(x * 1.06, y * 1.06, m.title(), rotation=rot, rotation_mode="anchor", fontsize=8, color=t["ink"],
                ha="left" if -90 <= ang <= 90 else "right", va="center")
    top2 = sorted(camps, key=lambda c: -len(camp_models[c]))[:2]  # 차종이 가장 많은 두 건은 점을 키워 구분
    ax.scatter(*zip(*[pos[("c", c)] for c in top2]), s=190, c=t["campaign"], edgecolors=t["ring"], linewidths=1.5, zorder=4)
    # 브랜드 구간 표시(무채색 글자): 바깥 원에서 브랜드별 가운데 위치
    for make in ("HYUNDAI", "GENESIS", "KIA"):
        idx = [i for i, m in enumerate(models) if model_make[m] == make]
        if not idx:
            continue
        a0 = math.pi / 2 - 2 * math.pi * (idx[0] + 0.25) / len(models)
        a1 = math.pi / 2 - 2 * math.pi * (idx[-1] + 0.75) / len(models)
        arc = [a0 + (a1 - a0) * k / 60 for k in range(61)]
        ax.plot([1.58 * math.cos(a) for a in arc], [1.58 * math.sin(a) for a in arc], color=t["muted"], lw=2,
                solid_capstyle="round")
        am = (a0 + a1) / 2
        ax.text(1.7 * math.cos(am), 1.7 * math.sin(am), make.title(), fontsize=12, color=t["muted"], ha="center",
                va="center", fontweight="bold")
    ax.set_xlim(-1.9, 1.9); ax.set_ylim(-1.9, 1.9)
    leg = ax.legend(loc="lower left", frameon=False, fontsize=10, labelcolor=t["ink2"])
    for h in leg.legend_handles:
        h.set_sizes([60])
    heading(ax, t, "부품 하나에서 브랜드를 넘어 퍼지는 리콜: ABS 제어 모듈",
            "SPARQL 경로 한 번으로 나오는 답. 문서 상위 10개만 보는 RAG는 이 범위를 모으지 못했다(질문 M1, M2).")
    ax.text(0, 0.995, "큰 파란 점: 차종이 가장 많은 캠페인 " + ", ".join(f"{c}({len(camp_models[c])}개 차종)" for c in top2)
            + ". 바깥 호: 브랜드 구간.", transform=ax.transAxes, fontsize=9.5, color=t["ink2"], va="bottom", ha="left")
    path = OUT / f"graph_abs_{theme}.png"
    fig.savefig(path, facecolor=t["surface"], bbox_inches="tight")
    plt.close(fig)
    return path


def main() -> None:
    g = build_overview()
    print(f"overview nodes={g.number_of_nodes()} edges={g.number_of_edges()}")
    for theme in THEMES:
        print(draw_overview(g, theme))
        print(draw_abs(theme))


if __name__ == "__main__":
    main()
