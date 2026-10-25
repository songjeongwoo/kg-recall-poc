"""리콜 지식그래프 질의 에이전트를 A2A(Agent2Agent) 서버로 노출한다. a2a-sdk 1.x(A2A 사양 1.0) 기준.

    python -m kgpoc.a2a_server            # http://localhost:9999
    curl http://localhost:9999/.well-known/agent-card.json

MCP 서버(mcp_server.py)는 그래프를 '도구'로 내준다. 호출하는 쪽 LLM이 SPARQL을 직접 쓰거나 고정 질의를 고른다.
A2A 서버는 같은 그래프를 '에이전트'로 내준다. 호출하는 쪽은 자연어로 일을 맡기고, 이 에이전트가 질의 작성,
실행, 재시도, 답변을 스스로 처리한 뒤 작업(Task) 상태와 결과물(Artifact)로 돌려준다.
질문이 모호해 결과가 없으면 TASK_STATE_INPUT_REQUIRED로 되묻고, 같은 작업에서 보충 질문을 받으면 이어서 처리한다.
"""
from __future__ import annotations

import asyncio
import os

import uvicorn
from starlette.applications import Starlette

from a2a.helpers.proto_helpers import new_task_from_user_message, new_text_part
from a2a.server.agent_execution.agent_executor import AgentExecutor
from a2a.server.agent_execution.context import RequestContext
from a2a.server.events.event_queue_v2 import EventQueue
from a2a.server.request_handlers.default_request_handler_v2 import DefaultRequestHandlerV2
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks.inmemory_task_store import InMemoryTaskStore
from a2a.server.tasks.task_updater import TaskUpdater
from a2a.types.a2a_pb2 import AgentCapabilities, AgentCard, AgentInterface, AgentSkill, Role

from .graph_qa import answer

MODEL = os.environ.get("KGPOC_MODEL", "sonnet")


class RecallGraphExecutor(AgentExecutor):
    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        task = context.current_task
        if task is None:
            task = new_task_from_user_message(context.message)
            await event_queue.enqueue_event(task)
        updater = TaskUpdater(event_queue, task.id, task.context_id)

        # 같은 작업에서 보충 입력을 받은 경우, 이전 사용자 메시지와 합쳐 하나의 질문으로 본다
        history = [p.text for m in task.history if m.role == Role.ROLE_USER for p in m.parts if p.text]
        current = context.get_user_input()
        question = " ".join(dict.fromkeys(history + [current])) if history else current

        await updater.start_work(updater.new_agent_message([new_text_part("Writing and running SPARQL over the recall graph...")]))
        ga = await asyncio.to_thread(answer, question, MODEL)  # LLM 호출은 블로킹이라 스레드로 넘긴다

        if not ga.found:
            await updater.requires_input(updater.new_agent_message([new_text_part(
                "No matching recalls were found. Please add a vehicle model, model year, component, "
                "or recall number (for example: '2021 SANTA FE' or 'ABS control module').")]))
            return

        await updater.add_artifact([new_text_part(ga.rows_markdown)], name="evidence-rows",
                                   metadata={"sparql": ga.sparql, "row_count": ga.row_count})
        await updater.complete(updater.new_agent_message([new_text_part(ga.answer)]))

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        task = context.current_task
        if task is not None:
            await TaskUpdater(event_queue, task.id, task.context_id).cancel()


def agent_card(base_url: str) -> AgentCard:
    return AgentCard(
        name="Recall Knowledge Graph Agent",
        description="Answers questions about Hyundai, Kia and Genesis vehicle recalls (NHTSA, 408 campaigns since 2010) "
                    "by writing SPARQL over an ontology-validated knowledge graph. Returns the answer plus evidence rows.",
        version="0.1.0",
        supported_interfaces=[AgentInterface(url=base_url, protocol_binding="JSONRPC", protocol_version="1.0")],
        capabilities=AgentCapabilities(streaming=True, push_notifications=False),
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain", "text/markdown"],
        skills=[AgentSkill(
            id="recall-graph-qa", name="Recall graph question answering",
            description="Multi-hop and aggregate questions about recalls: models, model years, components, hazards, "
                        "remedies, advisories, report dates.",
            tags=["recall", "knowledge-graph", "sparql", "automotive"],
            examples=["Which models were recalled for the ABS control module?",
                      "List every recall that covers the 2021 Hyundai Santa Fe."],
        )],
    )


def build_app(host: str = "localhost", port: int = 9999) -> Starlette:
    card = agent_card(f"http://{host}:{port}/")
    handler = DefaultRequestHandlerV2(agent_executor=RecallGraphExecutor(), task_store=InMemoryTaskStore(), agent_card=card)
    return Starlette(routes=create_agent_card_routes(card) + create_jsonrpc_routes(handler, rpc_url="/"))


if __name__ == "__main__":
    uvicorn.run(build_app(), host="localhost", port=9999)
