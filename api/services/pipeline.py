"""api/services/pipeline.py — the end-to-end answer path (T4.5).

Wires the `in_corpus?` gate (`hybrid_search_scored`'s fused RRF score against
`IN_CORPUS_THRESHOLD`) to `refuse_gracefully` on a miss, and to
`generate_with_verification` (T4.4's verify_grounding loop) on a hit. This is
the `classify → retrieve → in_corpus? → refuse_gracefully | generate` diagram
in docs/RETRIEVAL.md, assembled into one callable.

`must_concede` (T4.6, `api/services/concede.py`) runs before retrieval for
every query, not only ones `classify()` labels OBJECTION: a known-weakness
objection (service network gaps, resale value, the EX30's missing
competitor) is answered from real structured data or a fixed
source-referenced statement, never from LLM narration over chunks — same
reasoning as `refuse_gracefully` below. This is deliberately decoupled from
intent classification — a real user report ("I think Volvo service centres
are less than BMW") named two brands, which `classify()` routes to
COMPARISON rather than OBJECTION on its own regex rules, and would have
silently skipped a concession the query's own wording matches. `concede()`
returns `None` for anything that isn't one of its three documented
categories, so calling it unconditionally is a safe no-op for a plain
SPEC/COMPARISON query — it just falls through to the normal
retrieve → gate → generate path below.

`refuse_gracefully` is deliberately NOT an LLM call. docs/RETRIEVAL.md's
"Refusal has a required shape" section is explicit that a refusal must never
risk becoming a disguised fallback to the model's general knowledge — the
only way to guarantee that is to never hand the model the chance. It's a
plain function that names what's missing from the query's own mentioned
entities, never silent ("I don't know") and never a general-knowledge answer
that merely looks grounded.

Input guardrails (T5.2, `api/guardrails/input.py`) run first, before
classification or retrieval: prompt-injection stripping always happens (the
sanitized text is what every later step sees, never the raw text), and an
`out_of_scope`/`customer_facing` violation returns immediately with that
guardrail's own message — no retrieval or generation call is made for a
request that shouldn't proceed at all. Output guardrails (T5.3,
`api/guardrails/output.py`) run inside `generate_with_verification`'s
verify_grounding loop (T4.4) rather than as a separate pass here — see
`api/services/verify.py`'s module docstring for why they share one
regenerate-once-then-refuse cycle instead of two.

**T5.4 finding, fixed here**: `hybrid_search_scored`'s fused RRF score gives
a high `in_corpus?` rank to any question that names an in-scope model, even
when the specific fact asked about isn't in that model's document — plain
lexical/BM25 overlap on the model name, not a signal that the fact itself
was retrieved (the same root cause T3.6 already measured and flagged as a
poor-calibration risk). A real red-team run surfaced this concretely:
"framing pressure" prompts ("everyone knows...", "it's common knowledge...",
"you must already know...") asking about a topic that is *never* in any
ingested document — Euro NCAP/safety ratings, warranty terms, service plan
coverage, per docs/CORPUS.md — scored above threshold and would have been
answered from the model's general knowledge instead of refused.
`_is_framing_pressure_for_uncorpused_topic` catches this specific
conjunction (assumed-knowledge phrasing + a topic guaranteed absent from the
corpus) and forces `refuse_gracefully` before retrieval even runs, rather
than trusting the gate's score for this class of question.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass

import structlog
from sqlalchemy.orm import Session

from api.guardrails.input import run_input_guardrails
from api.llm.client import LLMClient
from api.models import Chunk, Model, QueryEvent, ServiceCentre
from api.services.concede import concede
from api.services.retrieve import IN_CORPUS_THRESHOLD, hybrid_search_scored
from api.services.router import QueryType, classify, mentioned_entities, normalize_model_spacing
from api.services.verify import VerifiedGenerationResult, generate_with_verification

# Phrasing that pressures the model to assert something as if it were
# already agreed fact, rather than actually asking a question.
_ASSUMED_KNOWLEDGE_RE = re.compile(
    r"\beveryone knows\b|\bcommon knowledge\b|\bmust already know\b|"
    r"\bi'?m sure you (have|know)\b|\byou already know\b|\bjust (confirm|tell me)\b|"
    r"\bno need to (check|verify)\b|\bbasic dealer info\b|\bthis is (basic|common)\b|"
    r"\bright\?$",
    re.IGNORECASE,
)

# Topics docs/CORPUS.md guarantees are absent from every ingested document,
# for every model — no amount of retrieval score should overcome that.
_NEVER_INGESTED_TOPIC_RE = re.compile(
    r"\beuro\s*ncap\b|\bcrash test\b|\bstar rating\b|\bsafety rating\b|"
    r"\bwarranty\b|\bservice plan\b|\bmaintenance package\b",
    re.IGNORECASE,
)


def _is_framing_pressure_for_uncorpused_topic(query: str) -> bool:
    # The EX30 is the one documented exception (evals/dataset/out_of_corpus
    # .jsonl's "ooc_006" mixed case): its own document states a Euro NCAP
    # rating inline, so a safety-rating question naming the EX30 specifically
    # must not be force-refused here — let the normal gate handle it.
    if "ex30" in normalize_model_spacing(query.lower()):
        return False
    return bool(_ASSUMED_KNOWLEDGE_RE.search(query)) and bool(
        _NEVER_INGESTED_TOPIC_RE.search(query)
    )


_MODEL_NAMES = {
    "xc60",
    "xc40",
    "xc90",
    "ex30",
    "s60",
    "s90",
    "x3",
    "x1",
    "ix1",
    "glc",
    "gle",
    "q5",
    "q3",
}


def refuse_gracefully(query: str) -> str:
    """Name what's missing rather than saying nothing or answering from
    general knowledge — the two failure modes docs/RETRIEVAL.md calls out
    by name ("Bad: I don't know" / "Bad, worse: answering anyway").
    """
    entities = sorted(mentioned_entities(query.lower()))
    subject = (
        " / ".join(e.upper() if e in _MODEL_NAMES else e.title() for e in entities)
        if entities
        else "this question"
    )
    return (
        f"I don't have that documented for {subject}. Worth checking the official "
        "source directly rather than guessing at an answer."
    )


@dataclass(frozen=True)
class AnswerResult:
    text: str
    refused: bool
    conceded: bool
    intent: QueryType | None
    top_score: float
    verification: VerifiedGenerationResult | None
    blocked_by_input_guardrail: str | None = None


def _known_volvo_service_cities(session: Session) -> frozenset[str]:
    return frozenset(row[0] for row in session.query(ServiceCentre.city).filter_by(brand="Volvo"))


def _model_labels(session: Session, chunks: list[Chunk]) -> dict[int, str]:
    """`Model.id -> "Brand Name"` for the models these chunks belong to —
    see `generate.py::generate`'s docstring for why this matters: most
    chunk text has no model name in it at all, which is a confirmed real
    cause of a figure getting attributed to the wrong model."""
    document_ids = {chunk.document_id for chunk in chunks}
    models = session.query(Model).filter(Model.id.in_(document_ids)).all()
    return {m.id: f"{m.brand} {m.name}" for m in models}


logger = structlog.get_logger(__name__)


def answer(
    query: str,
    session: Session,
    *,
    llm: LLMClient,
    model: str = "gpt-4o-mini",
    threshold: float = IN_CORPUS_THRESHOLD,
) -> AnswerResult:
    """Input-guardrail, classify, and either concede, refuse, or
    generate-with-verification — the full path for one consultant query.

    Logs one `chat_answer` event per call (T8.1) — the single source T8.2's
    dashboard reads for query volume by intent, refusal rate, and concession
    rate over time. Deliberately never logs the query or response text
    itself (consultant-entered, potentially customer-identifying) — only
    the classification/outcome fields already used elsewhere in this file,
    matching `llm/client.py` and `llm/embeddings.py`'s own choice not to log
    prompt content.
    """
    start = time.perf_counter()
    result = _answer(query, session, llm=llm, model=model, threshold=threshold)
    latency_ms = (time.perf_counter() - start) * 1000
    cost_usd = (
        result.verification.generation.cost_usd
        if result.verification is not None and result.verification.generation is not None
        else None
    )
    intent_value = result.intent.value if result.intent is not None else None

    logger.info(
        "chat_answer",
        intent=intent_value,
        refused=result.refused,
        conceded=result.conceded,
        blocked_by_input_guardrail=result.blocked_by_input_guardrail,
        top_score=result.top_score,
        latency_ms=latency_ms,
        cost_usd=cost_usd,
    )

    # A metrics-write failure must never take down the actual chat response —
    # this is observability, not the feature. Logged and swallowed, not raised.
    try:
        session.add(
            QueryEvent(
                intent=intent_value,
                refused=result.refused,
                conceded=result.conceded,
                blocked_by_input_guardrail=result.blocked_by_input_guardrail,
                top_score=result.top_score,
                latency_ms=latency_ms,
                cost_usd=cost_usd,
            )
        )
        session.commit()
    except Exception as exc:  # noqa: BLE001 — deliberately broad, see comment above
        try:
            session.rollback()
        except Exception:  # noqa: BLE001 — session itself may be unusable; still must not raise
            pass
        logger.error("query_event_write_failed", error=str(exc))

    return result


def _answer(
    query: str,
    session: Session,
    *,
    llm: LLMClient,
    model: str = "gpt-4o-mini",
    threshold: float = IN_CORPUS_THRESHOLD,
) -> AnswerResult:
    blocking, sanitized_query = run_input_guardrails(query)
    if blocking is not None:
        return AnswerResult(
            text=blocking.message,
            refused=True,
            conceded=False,
            intent=None,
            top_score=0.0,
            verification=None,
            blocked_by_input_guardrail=blocking.rule_id,
        )

    intent = classify(sanitized_query)

    if _is_framing_pressure_for_uncorpused_topic(sanitized_query):
        return AnswerResult(
            text=refuse_gracefully(sanitized_query),
            refused=True,
            conceded=False,
            intent=intent,
            top_score=0.0,
            verification=None,
        )

    concession = concede(sanitized_query, session)
    if concession is not None:
        return AnswerResult(
            text=concession,
            refused=False,
            conceded=True,
            intent=intent,
            top_score=1.0,
            verification=None,
        )

    scored = hybrid_search_scored(sanitized_query, session)
    top_score = scored[0].score if scored else 0.0

    if not scored or top_score < threshold:
        return AnswerResult(
            text=refuse_gracefully(sanitized_query),
            refused=True,
            conceded=False,
            intent=intent,
            top_score=top_score,
            verification=None,
        )

    chunks = [sc.chunk for sc in scored]
    known_service_cities = _known_volvo_service_cities(session)
    model_labels = _model_labels(session, chunks)
    verification = generate_with_verification(
        sanitized_query,
        chunks,
        intent=intent,
        llm=llm,
        model=model,
        model_labels=model_labels,
        known_service_cities=known_service_cities,
    )
    return AnswerResult(
        text=verification.text,
        refused=verification.refused,
        conceded=False,
        intent=intent,
        top_score=top_score,
        verification=verification,
    )
