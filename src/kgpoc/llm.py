"""JSON 스키마를 지키는 LLM 호출 한 곳. 평가의 모든 방식이 같은 모델, 같은 호출 방식을 쓰게 한다.

호출마다 비용(API 가격 환산, Claude Code CLI가 보고하는 total_cost_usd)과 소요 시간을 USAGE에 쌓는다.
"""
from __future__ import annotations

import json
import subprocess
import threading
import time

# 짧은 이름 → 모델 ID. CLI 별칭(sonnet, haiku)은 각각 claude-sonnet-5-5, claude-haiku-5-5로 풀린다(2026-10-25 확인).
MODELS = {
    "haiku": "claude-haiku-5-5",
    "sonnet": "claude-sonnet-5-5",
    "opus": "claude-opus-5-5",
    "fable": "claude-fable-5-1",
}

# 사용자 환경의 MCP 서버 도구 정의(약 7.5만 토큰)와 사용자 설정이 호출마다 문맥에 붙지 않게 막는다.
# 막지 않으면 Haiku 짧은 호출 비용이 약 100배가 되고, 평가 문맥에 무관한 도구 설명이 섞인다(2026-10-25 측정).
ISOLATION = ["--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}', "--setting-sources", "project"]

_local = threading.local()


def usage_reset() -> None:
    _local.usage = {"calls": 0, "cost_usd": 0.0, "llm_seconds": 0.0}


def usage_get() -> dict:
    return dict(getattr(_local, "usage", {"calls": 0, "cost_usd": 0.0, "llm_seconds": 0.0}))


def ask_json(system: str, prompt: str, schema: dict, model: str | None = "sonnet", timeout: int = 900) -> dict:
    """로컬 Claude Code CLI(`claude -p`)로 호출한다. 도구는 끄고 세션은 저장하지 않는다."""
    cmd = ["claude", "-p", "--output-format", "json", "--no-session-persistence",
           "--tools", "", *ISOLATION, "--system-prompt", system, "--json-schema", json.dumps(schema)]
    if model:
        cmd += ["--model", MODELS.get(model, model)]
    t0 = time.time()
    r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, encoding="utf-8", timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"claude exited {r.returncode}: {r.stderr[:500]}")
    env = json.loads(r.stdout)
    u = getattr(_local, "usage", None)
    if u is not None:
        u["calls"] += 1
        u["cost_usd"] += float(env.get("total_cost_usd") or 0)
        u["llm_seconds"] += time.time() - t0
    if isinstance(env.get("structured_output"), dict):
        return env["structured_output"]
    text = env.get("result", "")
    return json.loads(text[text.find("{"): text.rfind("}") + 1])
