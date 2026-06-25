"""Primary engine — LangGraph deepagents (the AI-Q deep-research pattern).

Used for grounded Q&A over a processed case (the agent decides when to search the
vector store vs. read the graph) and for the Critic synthesis step.
"""
from __future__ import annotations

import json

from langchain_openai import ChatOpenAI

from ..llm import structured_complete, text_client
from ..models import CaseReport
from ..settings import get_settings
from ..tools import graph_view, query_case

CHAT_INSTRUCTIONS = (
    "You are Sherlock, a forensic investigation co-agent. Answer questions about "
    "the active case using ONLY the tools and evidence available. Every factual "
    "claim must cite an asset id. If evidence is insufficient, say so — never "
    "speculate. You advise; the human investigator decides."
)

CRITIC_SYSTEM = (
    "You are the Critic in a deep-research investigation pipeline. Given collected "
    "entities, relationships, sentiments and graph analytics, synthesize a concise, "
    "defensible CaseReport. Drop any relationship lacking evidence. Populate "
    "'citations' with the asset ids actually relied upon. Be accurate, not verbose."
)


class DeepAgentsEngine:
    name = "deepagents"

    def _model(self) -> ChatOpenAI:
        s = get_settings()
        return ChatOpenAI(
            base_url=s.text_base_url, api_key=s.serving_api_key,
            model=s.text_served, temperature=0.1,
        )

    def _agent(self, case_id: str):
        from deepagents import create_deep_agent
        from langchain_core.tools import tool

        @tool
        def search_case(query: str) -> str:
            """Semantic search over the case material. Returns snippets with sources."""
            return json.dumps(query_case(case_id, query, k=5))

        @tool
        def read_graph() -> str:
            """Return the entity-relationship graph (nodes + edges) for the case."""
            return json.dumps(graph_view(case_id))

        return create_deep_agent(
            tools=[search_case, read_graph],
            instructions=CHAT_INSTRUCTIONS,
            model=self._model(),
        )

    def chat(self, case_id: str, message: str, history: list[dict] | None = None) -> str:
        agent = self._agent(case_id)
        messages = (history or []) + [{"role": "user", "content": message}]
        result = agent.invoke({"messages": messages})
        return result["messages"][-1].content

    def reason_report(self, case_id: str, context: dict) -> CaseReport:
        client, model = text_client()
        messages = [
            {"role": "system", "content": CRITIC_SYSTEM},
            {
                "role": "user",
                "content": (
                    f"case_id: {case_id}\n\nCollected findings (JSON):\n"
                    f"{json.dumps(context, default=str)[:12000]}\n\n"
                    "Return a CaseReport."
                ),
            },
        ]
        report = structured_complete(client, model, messages, CaseReport, max_tokens=3072)
        report.case_id = case_id
        return report
