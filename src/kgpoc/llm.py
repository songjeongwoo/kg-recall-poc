"""JSON 스키마를 지키는 LLM 호출 한 곳. 평가의 두 방식(벡터 RAG, 그래프 질의)이 같은 모델과 같은 호출 방식을 쓰게 한다."""
from __future__ import annotations

import json
import subprocess


def ask_json(system: str, prompt: str, schema: dict, model: str | None = "sonnet", timeout: int = 600) -> dict:
    """로컬 Claude Code CLI(`claude -p`)로 호출한다. 도구는 끄고 세션은 저장하지 않는다."""
    cmd = ["claude", "-p", "--output-format", "json", "--no-session-persistence",
           "--tools", "", "--system-prompt", system, "--json-schema", json.dumps(schema)]
    if model:
        cmd += ["--model", model]
    r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, encoding="utf-8", timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"claude exited {r.returncode}: {r.stderr[:500]}")
    env = json.loads(r.stdout)
    if isinstance(env.get("structured_output"), dict):
        return env["structured_output"]
    text = env.get("result", "")
    return json.loads(text[text.find("{"): text.rfind("}") + 1])
