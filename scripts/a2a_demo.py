"""A2A 클라이언트 데모: Agent Card 조회 → 모호한 질문(되묻기) → 같은 작업에 보충 입력 → 완료.

    python -m kgpoc.a2a_server          # 다른 터미널
    python scripts/a2a_demo.py
"""
from __future__ import annotations

import asyncio
import sys
import uuid

import httpx
from google.protobuf.json_format import MessageToDict

from a2a.client import ClientConfig, create_client
from a2a.helpers.proto_helpers import new_text_part
from a2a.types.a2a_pb2 import Message, Role, SendMessageRequest

URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:9999"


def show(resp) -> tuple[str | None, str | None, str | None]:
    """스트림 이벤트 한 개를 한 줄로 출력하고 (task_id, context_id, state)를 돌려준다."""
    kind = resp.WhichOneof("payload")
    obj = getattr(resp, kind)
    d = MessageToDict(obj)
    if kind == "task":
        print(f"  [task] id={obj.id[:8]} state={d.get('status', {}).get('state')}")
        return obj.id, obj.context_id, d.get("status", {}).get("state")
    if kind == "status_update":
        state = d.get("status", {}).get("state")
        texts = [p.get("text", "") for p in d.get("status", {}).get("message", {}).get("parts", [])]
        print(f"  [status] {state}: {' '.join(texts)[:300]}")
        return obj.task_id, obj.context_id, state
    if kind == "artifact_update":
        a = d.get("artifact", {})
        print(f"  [artifact] {a.get('name')} sparql={a.get('metadata', {}).get('sparql', '')[:120]!r}")
        print("   " + a.get("parts", [{}])[0].get("text", "")[:400].replace("\n", "\n   "))
        return obj.task_id, obj.context_id, None
    print(f"  [{kind}] {str(d)[:300]}")
    return None, None, None


async def send(client, text: str, task_id: str | None = None, context_id: str | None = None):
    msg = Message(message_id=str(uuid.uuid4()), role=Role.ROLE_USER, parts=[new_text_part(text)])
    if task_id:
        msg.task_id = task_id
    if context_id:
        msg.context_id = context_id
    last = (None, None, None)
    async for resp in client.send_message(SendMessageRequest(message=msg)):
        t, c, s = show(resp)
        last = (t or last[0], c or last[1], s or last[2])
    return last


async def main() -> None:
    async with httpx.AsyncClient(timeout=300) as http:
        card = (await http.get(f"{URL}/.well-known/agent-card.json")).json()
        print(f"Agent Card: {card['name']} / skills={[s['id'] for s in card['skills']]} / "
              f"interfaces={[(i['protocolBinding'], i['protocolVersion']) for i in card['supportedInterfaces']]}")
        client = await create_client(URL, client_config=ClientConfig(streaming=True, httpx_client=http))

        print("\n1) Vague question")
        task_id, context_id, state = await send(client, "Were there recalls for the XYZ-9000 crossover?")
        if state == "TASK_STATE_INPUT_REQUIRED":
            print("\n2) Follow-up on the same task (input-required -> resumed)")
            await send(client, "I meant the 2021 Hyundai SANTA FE. List its recalls.", task_id, context_id)

        print("\n3) Multi-hop question")
        await send(client, "Which Genesis models were recalled for a detailed component category that was also recalled on the Kia Telluride?")


if __name__ == "__main__":
    asyncio.run(main())
