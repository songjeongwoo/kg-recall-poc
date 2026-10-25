"""리콜 결함/결과/조치 문장에서 온톨로지 통제 어휘(위험 유형, 조치 유형)와 원인 구절을 LLM으로 뽑는다.

백엔드
- claude-cli (기본): 로컬 Claude Code 구독으로 `claude -p` 실행. API key 불필요.
- anthropic: ANTHROPIC_API_KEY 필요.

    python -m kgpoc.extract --limit 20            # 앞 20건만 시험
    python -m kgpoc.extract                       # 전체(이미 뽑은 캠페인은 건너뜀)

결과는 pydantic으로 1차 검사(어휘 밖 값이면 그 건만 버림)하고, 그래프 적재 때 SHACL로 2차 검사한다.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

HAZARDS = ["Fire", "Crash", "Injury", "LossOfDrivePower", "BrakingLoss", "SteeringLoss",
           "VisibilityLoss", "OccupantProtectionLoss", "RegulatoryNoncompliance", "OtherHazard"]
REMEDIES = ["Replace", "Repair", "Inspect", "SoftwareUpdate", "Relabel", "Repurchase", "OtherRemedy"]
PROMPT_VERSION = "v1"


class Extraction(BaseModel):
    campaign: str
    hazards: list[Literal[tuple(HAZARDS)]] = Field(min_length=1, max_length=4)  # type: ignore[valid-type]
    remedy_types: list[Literal[tuple(REMEDIES)]] = Field(min_length=1, max_length=2)  # type: ignore[valid-type]
    root_cause: str = Field(min_length=3, max_length=200)


SCHEMA = {
    "type": "object",
    "properties": {"items": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "campaign": {"type": "string"},
            "hazards": {"type": "array", "items": {"type": "string", "enum": HAZARDS}, "minItems": 1, "maxItems": 4},
            "remedy_types": {"type": "array", "items": {"type": "string", "enum": REMEDIES}, "minItems": 1, "maxItems": 2},
            "root_cause": {"type": "string"},
        },
        "required": ["campaign", "hazards", "remedy_types", "root_cause"],
        "additionalProperties": False,
    }}},
    "required": ["items"],
    "additionalProperties": False,
}

SYSTEM = f"""You annotate NHTSA vehicle recall summaries for a knowledge graph.
For each campaign return:
- hazards: the safety consequences stated in the consequence/defect text, chosen ONLY from {HAZARDS}.
  Use Crash when the text says the risk of a crash increases. Use Injury when it says injury risk increases.
  Use OccupantProtectionLoss for airbag/seat belt/seat protection degradation. Use RegulatoryNoncompliance
  when the recall is mainly a FMVSS noncompliance. Use OtherHazard only if none fits.
- remedy_types: what dealers will do, chosen ONLY from {REMEDIES}. Max 2, most important first.
- root_cause: the underlying cause in one short English phrase (<= 20 words), e.g.
  "contaminated ABS module circuit board" or "improperly torqued fasteners". Do not restate the consequence.
Return JSON only, one item per input campaign, same campaign ids."""


def batch_prompt(camps: list[dict]) -> str:
    lines = []
    for c in camps:
        lines.append(json.dumps({
            "campaign": c["campaign"],
            "components": c["components"],
            "defect": c["defect"][:2500],
            "consequence": c["consequence"][:800],
            "corrective": c["corrective"][:1500],
        }, ensure_ascii=False))
    return "Annotate these campaigns:\n" + "\n".join(lines)


def call_claude_cli(prompt: str, model: str | None) -> dict:
    cmd = ["claude", "-p", "--output-format", "json", "--no-session-persistence",
           "--tools", "", "--system-prompt", SYSTEM, "--json-schema", json.dumps(SCHEMA)]
    if model:
        cmd += ["--model", model]
    r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, encoding="utf-8", timeout=600)
    if r.returncode != 0:
        raise RuntimeError(f"claude exited {r.returncode}: {r.stderr[:500]}")
    env = json.loads(r.stdout)
    if isinstance(env.get("structured_output"), dict):
        return env["structured_output"]
    text = env.get("result", "")
    start, end = text.find("{"), text.rfind("}")
    return json.loads(text[start:end + 1])


def call_anthropic(prompt: str, model: str | None) -> dict:
    import anthropic  # optional dependency: pip install -e ".[llm]"
    client = anthropic.Anthropic()
    msg = client.messages.create(
        model=model or os.environ.get("KGPOC_MODEL", "claude-haiku-4-5"),
        max_tokens=4000, system=SYSTEM + "\nRespond with a JSON object {\"items\": [...]} and nothing else.",
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(b.text for b in msg.content if b.type == "text")
    return json.loads(text[text.find("{"): text.rfind("}") + 1])


BACKENDS = {"claude-cli": call_claude_cli, "anthropic": call_anthropic}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--campaigns", type=Path, default=Path("data/processed/campaigns.jsonl"))
    ap.add_argument("--out", type=Path, default=Path("data/extracted/extractions.jsonl"))
    ap.add_argument("--backend", choices=list(BACKENDS), default="claude-cli")
    ap.add_argument("--model", default=None, help="예: haiku, sonnet (claude-cli) 또는 API 모델 ID")
    ap.add_argument("--batch", type=int, default=10)
    ap.add_argument("--limit", type=int, default=None)
    a = ap.parse_args()

    camps = [json.loads(l) for l in a.campaigns.open(encoding="utf-8")]
    done = set()
    if a.out.exists():
        done = {json.loads(l)["campaign"] for l in a.out.open(encoding="utf-8") if l.strip()}
    todo = [c for c in camps if c["campaign"] not in done]
    if a.limit is not None:
        todo = todo[: max(0, a.limit - len(done))] if a.limit > len(done) else []
    print(f"total={len(camps)} done={len(done)} todo={len(todo)} backend={a.backend}", flush=True)

    a.out.parent.mkdir(parents=True, exist_ok=True)
    rejected = a.out.with_name("rejected.jsonl")
    call = BACKENDS[a.backend]
    ok = bad = 0
    for i in range(0, len(todo), a.batch):
        chunk = todo[i: i + a.batch]
        ids = {c["campaign"] for c in chunk}
        t0 = time.time()
        try:
            res = call(batch_prompt(chunk), a.model)
        except Exception as ex:  # 한 묶음 실패는 건너뛰고 다음 실행에서 다시 시도
            print(f"  batch {i // a.batch} failed: {ex}", file=sys.stderr, flush=True)
            continue
        with a.out.open("a", encoding="utf-8", newline="\n") as f, rejected.open("a", encoding="utf-8", newline="\n") as rf:
            for item in res.get("items", []):
                try:
                    e = Extraction.model_validate(item)
                    if e.campaign not in ids:
                        raise ValueError("unknown campaign id")
                    rec = e.model_dump() | {"model": a.model or "default", "backend": a.backend,
                                            "prompt_version": PROMPT_VERSION}
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    ok += 1
                except (ValidationError, ValueError) as ex:
                    rf.write(json.dumps({"item": item, "error": str(ex)[:300]}, ensure_ascii=False) + "\n")
                    bad += 1
        print(f"  batch {i // a.batch}: {len(chunk)} campaigns in {time.time() - t0:.0f}s (ok={ok} rejected={bad})", flush=True)
    print(f"done ok={ok} rejected={bad} -> {a.out}")


if __name__ == "__main__":
    main()
