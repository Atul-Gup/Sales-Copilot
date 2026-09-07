"""api/objection/graph.py — the objection LangGraph:
classify -> retrieve -> generate -> verify_grounding, with an abstain branch
on a low-confidence or unclassifiable objection, and a
generate <-> verify_grounding cycle (T4.4) that regenerates once on a
violation, then refuses.

This is the cycle docs/RETRIEVAL.md says actually justifies LangGraph here
("a chain can't express 'verify, and if it fails, go back and regenerate'").
T4.3 alone (classify/retrieve/generate, no loop) could have been three plain
function calls; T4.4's `generate -> verify_grounding -> generate` loop is
what a graph is for.
"""

from __future__ import annotations

from typing import Any, cast

from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph
from sqlalchemy.orm import Session

from api.llm.client import LLMClient
from api.llm.embeddings import EmbeddingClient
from api.objection.classify import CONFIDENCE_THRESHOLD, classify_objection
from api.objection.generate import abstain_response, generate_response, refuse_response
from api.objection.retrieve import retrieve_chunks, retrieve_facts
from api.objection.state import ObjectionState
from api.objection.verify import verify_grounding

# One initial generation plus one regeneration attempt, per docs/RETRIEVAL.md
# ("(attempts==1) -> refuse").
MAX_GENERATE_ATTEMPTS = 2


def build_objection_graph(
    *, llm: LLMClient, embedder: EmbeddingClient, session: Session
) -> CompiledStateGraph[Any, Any, Any, Any]:
    graph = StateGraph(ObjectionState)

    def classify_node(state: ObjectionState) -> dict[str, Any]:
        result = classify_objection(llm, state["objection_text"])
        return {"category": result.category, "confidence": result.confidence}

    def route_after_classify(state: ObjectionState) -> str:
        if state["category"] == "other" or state["confidence"] < CONFIDENCE_THRESHOLD:
            return "abstain"
        return "retrieve"

    def abstain_node(_state: ObjectionState) -> dict[str, Any]:
        return {"response": abstain_response(), "abstained": True}

    def retrieve_node(state: ObjectionState) -> dict[str, Any]:
        context = state.get("context") or {}
        facts = retrieve_facts(session, state["category"], context)
        chunks = retrieve_chunks(session, embedder, state["objection_text"])
        return {"facts": facts, "chunks": chunks}

    def generate_node(state: ObjectionState) -> dict[str, Any]:
        response = generate_response(
            llm, state["objection_text"], state.get("facts", []), state.get("chunks", [])
        )
        attempts = state.get("attempts", 0) + 1
        return {"response": response, "abstained": False, "attempts": attempts}

    def verify_node(state: ObjectionState) -> dict[str, Any]:
        violations = verify_grounding(
            state["category"],
            state.get("facts", []),
            state.get("chunks", []),
            state["response"],
        )
        return {"violations": violations}

    def route_after_verify(state: ObjectionState) -> str:
        violations = state.get("violations") or []
        if not violations:
            return "end"
        if state.get("attempts", 0) < MAX_GENERATE_ATTEMPTS:
            return "retry"
        return "refuse"

    def refuse_node(state: ObjectionState) -> dict[str, Any]:
        return {
            "response": refuse_response(state.get("violations", [])),
            "abstained": True,
            "refused": True,
        }

    # langgraph's add_node signature is generic in a way mypy can't match
    # against plain `ObjectionState -> dict` node functions — same friction
    # as every other vendor SDK boundary in this project (see
    # api/llm/embeddings.py's `# type: ignore[assignment]`).
    graph.add_node("classify_objection", cast(Any, classify_node))
    graph.add_node("abstain", cast(Any, abstain_node))
    graph.add_node("retrieve", cast(Any, retrieve_node))
    graph.add_node("generate", cast(Any, generate_node))
    graph.add_node("verify_grounding", cast(Any, verify_node))
    graph.add_node("refuse", cast(Any, refuse_node))

    graph.set_entry_point("classify_objection")
    graph.add_conditional_edges(
        "classify_objection",
        route_after_classify,
        {"abstain": "abstain", "retrieve": "retrieve"},
    )
    graph.add_edge("retrieve", "generate")
    graph.add_edge("generate", "verify_grounding")
    graph.add_conditional_edges(
        "verify_grounding",
        route_after_verify,
        {"end": END, "retry": "generate", "refuse": "refuse"},
    )
    graph.add_edge("refuse", END)
    graph.add_edge("abstain", END)

    return graph.compile()
