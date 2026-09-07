"""api/objection/state.py — shared types for the objection LangGraph (T4.3,
extended by T4.4 with the `attempts`/`violations`/`refused` fields the
`verify_grounding` loop needs).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TypedDict


@dataclass(frozen=True)
class RetrievedFact:
    """One Corpus A fact, always carrying its `source_id` — AGENTS.md rule 1."""

    claim: str
    source_id: int


@dataclass(frozen=True)
class RetrievedChunk:
    """One Corpus B chunk, with enough of its citation to verify it."""

    text: str
    document_title: str
    page: int | None
    source_id: int


@dataclass(frozen=True)
class ClassificationResult:
    category: str
    confidence: float


@dataclass(frozen=True)
class GeneratedResponse:
    what_is_true: str
    how_to_frame_it: str
    what_not_to_claim: str
    raw_text: str


class ObjectionState(TypedDict, total=False):
    objection_text: str
    context: dict[str, Any]
    category: str
    confidence: float
    facts: list[RetrievedFact]
    chunks: list[RetrievedChunk]
    response: GeneratedResponse
    abstained: bool
    attempts: int
    violations: list[str]
    refused: bool
