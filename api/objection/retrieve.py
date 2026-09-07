"""api/objection/retrieve.py — retrieve node (T4.3).

Corpus A: a direct SQL lookup per category — docs/RETRIEVAL.md: "Selection
is a SQL join off the matched objection category... exact, verifiable, no
similarity threshold." Corpus B: hybrid retrieval over `document_chunks`
(api/retrieval/hybrid.py, T4.2b). Reranking is deliberately skipped here —
T4.2c's measured ablation decided against adopting it on this corpus; flip
`retrieve_chunks` to call `api/retrieval/rerank.py::rerank` if that verdict
is later reversed with a real Anthropic key.

Three of the five known-weakness categories (price_positioning,
resale_value, brand_prestige, waiting_period) have no Corpus A fact table
backing them at all — docs/CORPUS.md and evals/dataset/concessions.jsonl
both record zero ingested data there. `retrieve_facts` returns an empty list
for those, which is the honest, correct result: T4.4's `must_concede` (built
on top of this node) still needs to concede those objections, just without a
sourced figure to cite (concessions.jsonl's `must_state_figure: false`).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.llm.embeddings import EmbeddingClient
from api.models import Brand, DocumentChunk, ServiceCentre, Source
from api.objection.state import RetrievedChunk, RetrievedFact
from api.retrieval.hybrid import hybrid_search
from api.services.spec_query import get_safety_ratings_for_model, get_specs_for_variant

DOCUMENT_CHUNK_TOP_K = 5


def _service_network_facts(session: Session, context: dict[str, Any]) -> list[RetrievedFact]:
    volvo_brand = context.get("volvo_brand") or "Volvo Cars"
    competitor_brand = context.get("competitor_brand")
    brand_names = [b for b in (volvo_brand, competitor_brand) if isinstance(b, str)]

    facts: list[RetrievedFact] = []
    for brand_name in brand_names:
        stmt = (
            select(ServiceCentre, Source)
            .join(Brand, ServiceCentre.brand_id == Brand.id)
            .join(Source, ServiceCentre.source_id == Source.id)
            .where(Brand.name == brand_name)
        )
        rows = session.execute(stmt).all()
        if not rows:
            continue
        cities = sorted({centre.city for centre, _source in rows})
        claim = f"{brand_name} has {len(rows)} ingested service centre(s): {', '.join(cities)}"
        facts.append(RetrievedFact(claim=claim, source_id=rows[0][1].id))
    return facts


def _spec_comparison_facts(session: Session, context: dict[str, Any]) -> list[RetrievedFact]:
    facts: list[RetrievedFact] = []
    for variant_id in context.get("variant_ids", []) or []:
        for spec in get_specs_for_variant(session, variant_id):
            value = spec.value_text if spec.value_text is not None else str(spec.value_num)
            unit = f" {spec.unit}" if spec.unit else ""
            facts.append(
                RetrievedFact(
                    claim=f"variant {variant_id} {spec.attribute}: {value}{unit}",
                    source_id=spec.source.id,
                )
            )
    for model_id in context.get("model_ids", []) or []:
        for rating in get_safety_ratings_for_model(session, model_id):
            facts.append(
                RetrievedFact(
                    claim=(
                        f"model {model_id} Euro NCAP {rating.year}: adult {rating.adult_score}%, "
                        f"child {rating.child_score}%, VRU {rating.vru_score}%, "
                        f"assist {rating.assist_score}%"
                    ),
                    source_id=rating.source.id,
                )
            )
    return facts


def retrieve_facts(session: Session, category: str, context: dict[str, Any]) -> list[RetrievedFact]:
    if category == "service_network":
        return _service_network_facts(session, context)
    if category == "spec_comparison":
        return _spec_comparison_facts(session, context)
    # price_positioning, resale_value, brand_prestige, waiting_period,
    # document_qa, other: no Corpus A fact table backs these — see module
    # docstring. An empty list is the correct, honest result.
    return []


def retrieve_chunks(
    session: Session,
    embedder: EmbeddingClient,
    query: str,
    *,
    k: int = DOCUMENT_CHUNK_TOP_K,
) -> list[RetrievedChunk]:
    result = hybrid_search(session, embedder, query, top_n=k)
    if not result.chunk_ids:
        return []
    rows = session.scalars(
        select(DocumentChunk).where(DocumentChunk.id.in_(result.chunk_ids))
    ).all()
    chunks_by_id = {chunk.id: chunk for chunk in rows}
    return [
        RetrievedChunk(
            text=chunks_by_id[chunk_id].text,
            document_title=chunks_by_id[chunk_id].document_title,
            page=chunks_by_id[chunk_id].page,
            source_id=chunks_by_id[chunk_id].source_id,
        )
        for chunk_id in result.chunk_ids
        if chunk_id in chunks_by_id
    ]
