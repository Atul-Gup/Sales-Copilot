"""evals/run_eval.py — run the eval metrics (T3.5) against whatever pipeline
actually exists today, and write a results snapshot (T3.6).

The SQL-only spec/comparison path (Phase 2: `spec_query.py`, `compare.py`),
TCO (T4.5, arithmetic-only, no LLM), and over-refusal (T5.5, input
guardrails against `specs.jsonl`, no LLM either) are live. The
objection-generation pipeline's own eval wiring (`honest_concession_rate`,
`judge_agreement_rate`) and the full red-team run (`refusal_accuracy`) are
measured separately by `evals/run_concession_eval.py` (T4.4) and
`evals/run_redteam_eval.py` (T5.4) respectively rather than folded into this
baseline — they report `null` here with a `blocked_on` note naming that
script rather than a fabricated number. What *is* real:

- Spec and comparison queries run against an in-memory SQLite database built by
  calling each brand's `ingest.<brand>.run(session)` directly (the same
  function `main()` uses against the real Postgres instance) — no live
  Postgres/docker required to produce this baseline, and it exercises the
  actual ingested corpus, not a synthetic fixture.
- `hallucinated_spec_rate` / `citation_validity` are measured against real
  claims pulled straight from that database via `spec_query.get_specs_for_variant`.
  Because this path has no LLM in the loop — it's a direct SQL read — both are
  expected to land at the trivial 0.0 / 1.0 baseline; the number that matters
  is that the code path runs end-to-end. These stop being trivial once T4.x's
  generation sits in front of the same facts.
- Latency is measured for real, separately for the spec, comparison, and
  objection paths (T6.1), by timing the actual service/graph calls. The
  objection path's timing uses a scripted LLM and embedder (no live
  `OPENAI_API_KEY`), so it measures the graph's real control flow and
  real SQL/hybrid-search calls, not real generation latency — see
  `run_objection_path`'s docstring.

Usage: `python -m evals.run_eval` (writes `evals/results/baseline.json`).
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from api.llm.client import CompletionResult, LLMClient, Message
from api.llm.embeddings import EmbeddingClient, EmbeddingResult
from api.models import Base, CarModel
from api.objection.graph import build_objection_graph
from api.services.compare import compare_variants
from api.services.spec_query import find_variants, get_specs_for_variant
from api.services.tco import TCOAssumptions, compute_five_year_tco
from evals.metrics import (
    Claim,
    GroundTruthFact,
    LatencySample,
    citation_validity,
    hallucinated_spec_rate,
    latency_percentiles,
    tco_accuracy,
)
from evals.run_specs_eval import run_specs_eval
from ingest import audi, bmw, mercedes, volvo

DATASET_DIR = Path(__file__).parent / "dataset"
RESULTS_DIR = Path(__file__).parent / "results"


def _load_jsonl(name: str) -> list[dict[str, Any]]:
    with (DATASET_DIR / name).open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def build_corpus_session() -> Session:
    """An in-memory DB populated by every brand's real ingest module — the
    same corpus the live system has, without needing a running Postgres.
    """
    engine = create_engine("sqlite:///:memory:")

    def _enable_fk(dbapi_connection: object, _connection_record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    event.listen(engine, "connect", _enable_fk)
    Base.metadata.create_all(engine)
    db = Session(engine)
    volvo.run(db)
    bmw.run(db)
    mercedes.run(db)
    audi.run(db)
    db.commit()
    return db


def run_spec_path(db: Session) -> tuple[list[Claim], list[GroundTruthFact], list[LatencySample]]:
    """Query every ingested variant's specs, timing each call and turning the
    result into both a `Claim` (what the path reports) and a `GroundTruthFact`
    (what's actually in the DB) — identical here since it's a direct read.
    """
    claims: list[Claim] = []
    facts: list[GroundTruthFact] = []
    samples: list[LatencySample] = []

    for variant in find_variants(db):
        model = db.get(CarModel, variant.model_id)
        variant_label = f"{model.name} {variant.name}" if model is not None else variant.name

        start = time.perf_counter()
        specs = get_specs_for_variant(db, variant.id)
        elapsed_ms = (time.perf_counter() - start) * 1000
        samples.append(LatencySample(path="spec", latency_ms=elapsed_ms))

        for spec in specs:
            value = spec.value_text if spec.value_text is not None else str(spec.value_num)
            claims.append(
                Claim(
                    variant_name=variant_label,
                    attribute=spec.attribute,
                    value=value,
                    cited_source_id=spec.source.id,
                )
            )
            facts.append(
                GroundTruthFact(
                    variant_name=variant_label,
                    attribute=spec.attribute,
                    value=value,
                    source_id=spec.source.id,
                )
            )

    return claims, facts, samples


def run_comparison_path(db: Session) -> list[LatencySample]:
    """Time `compare_variants` across every cross-brand pair of ingested
    variants — the comparison path's only job today; there's no separate
    claim/fact scoring beyond what the spec path already covers, since
    `compare_variants` is built directly on `get_specs_for_variant`.
    """
    variants = find_variants(db)
    samples: list[LatencySample] = []
    for i, a in enumerate(variants):
        for b in variants[i + 1 :]:
            if a.model_id == b.model_id:
                continue
            start = time.perf_counter()
            compare_variants(db, a.id, b.id)
            elapsed_ms = (time.perf_counter() - start) * 1000
            samples.append(LatencySample(path="comparison", latency_ms=elapsed_ms))
    return samples


_OBJECTION_SCRIPT = (
    '{"category": "spec_comparison", "confidence": 0.95}',
    "WHAT'S TRUE: The retrieved spec figure is stated above.\n"
    "HOW TO FRAME IT: Present it plainly with its source.\n"
    "WHAT NOT TO CLAIM: Nothing beyond the retrieved figure.",
)


class _ScriptedObjectionLLM:
    """Deterministic `LLMClient` stand-in for objection-path latency
    measurement — no live `OPENAI_API_KEY` in this sandbox, same as every
    other proxy in this project (`_HashEmbedder`, `_ScriptedConcessionLLM`).
    Cycles through `_OBJECTION_SCRIPT` (classify -> generate) once per
    `graph.invoke()` call — two calls now, not three: T6.4 replaced
    `verify_grounding`'s LLM-based claim extraction with a deterministic
    sentence split (`api.objection.verify.extract_claims_deterministic`),
    cutting one sequential LLM round-trip off every generation attempt.
    `spec_comparison` is deliberately not one of
    `verify.KNOWN_WEAKNESS_CATEGORIES`, so `check_concession` never fires
    and every run takes exactly this graph path
    (classify -> retrieve -> generate -> verify -> END) with no retry —
    what's timed is the graph's real control flow and real DB/hybrid-search
    calls, not real generation latency.
    """

    def __init__(self) -> None:
        self._index = 0

    def complete(self, _messages: list[Message], **_kwargs: Any) -> CompletionResult:
        text = _OBJECTION_SCRIPT[self._index % len(_OBJECTION_SCRIPT)]
        self._index += 1
        return CompletionResult(
            text=text,
            model="scripted-objection-proxy",
            input_tokens=0,
            output_tokens=0,
            cost_usd=None,
            latency_ms=0.0,
            retries=0,
        )


class _ZeroEmbedder:
    """Deterministic `EmbeddingClient` stand-in — same role as
    `run_retrieval_eval.py`'s `_HashEmbedder`, simplified since the
    objection-path timing run doesn't score retrieval quality, only exercises
    the real `hybrid_search` call against an empty `document_chunks` table.
    """

    def embed(self, texts: list[str], **_kwargs: Any) -> EmbeddingResult:
        return EmbeddingResult(
            vectors=[[0.0] for _ in texts],
            model="zero-embedder",
            input_tokens=0,
            cost_usd=None,
            latency_ms=0.0,
        )


def run_objection_path(db: Session, n_runs: int = 10) -> list[LatencySample]:
    """Time `n_runs` full `classify -> retrieve -> generate -> verify_grounding`
    graph invocations against a real ingested variant, using the scripted LLM
    and embedder above. This measures the graph's real control flow, real SQL
    fact retrieval, and real (empty) hybrid search — not real generation
    latency, since no live LLM is available. Re-run with a real
    `OPENAI_API_KEY` for a latency number worth citing end to end.
    """
    llm: LLMClient = _ScriptedObjectionLLM()  # type: ignore[assignment]
    embedder: EmbeddingClient = _ZeroEmbedder()  # type: ignore[assignment]
    graph = build_objection_graph(llm=llm, embedder=embedder, session=db)
    variant = find_variants(db)[0]

    samples: list[LatencySample] = []
    for _ in range(n_runs):
        start = time.perf_counter()
        graph.invoke(
            {
                "objection_text": "How does the boot space compare to the competitor?",
                "context": {"variant_ids": [variant.id]},
            }
        )
        elapsed_ms = (time.perf_counter() - start) * 1000
        samples.append(LatencySample(path="objection", latency_ms=elapsed_ms))
    return samples


def run_tco_cases(tco_entries: list[dict[str, Any]]) -> dict[str, float]:
    """`services/tco.py` (T4.5) against each `tco.jsonl` entry's own fixed
    `assumptions` — this is real arithmetic, not a stand-in, since TCO never
    depended on ingested data in the first place (every input is a caller
    assumption, per that module's docstring).
    """
    computed: dict[str, float] = {}
    for entry in tco_entries:
        a = entry["assumptions"]
        assumptions = TCOAssumptions(
            on_road_price_inr=a["on_road_price_inr"],
            annual_km=a["annual_km"],
            annual_maintenance_inr=a["annual_maintenance_inr"],
            annual_insurance_inr=a["annual_insurance_inr"],
            five_year_retained_value_pct=a["five_year_retained_value_pct"],
            fuel_efficiency_kmpl=a.get("fuel_efficiency_kmpl"),
            fuel_price_per_litre_inr=a.get("fuel_price_per_litre_inr"),
            consumption_kwh_per_100km=a.get("consumption_kwh_per_100km"),
            electricity_price_per_kwh_inr=a.get("electricity_price_per_kwh_inr"),
        )
        computed[entry["id"]] = compute_five_year_tco(assumptions).five_year_tco_inr
    return computed


def build_results() -> dict[str, Any]:
    db = build_corpus_session()
    try:
        claims, facts, spec_latency = run_spec_path(db)
        comparison_latency = run_comparison_path(db)
        objection_latency = run_objection_path(db)
    finally:
        db.close()

    latency = latency_percentiles(spec_latency + comparison_latency + objection_latency)

    concessions = _load_jsonl("concessions.jsonl")
    redteam = _load_jsonl("redteam.jsonl")
    tco = _load_jsonl("tco.jsonl")
    specs_eval = run_specs_eval()

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "pipeline_state": "Phase 2 only (SQL spec/comparison path). "
        "No LLM generation, objection handling, or guardrails exist yet.",
        "metrics": {
            "hallucinated_spec_rate": {
                "value": hallucinated_spec_rate(claims, facts),
                "n_claims": len(claims),
                "note": "Direct SQL read, no LLM in the loop yet — 0.0 is the "
                "expected floor, not evidence of a working generation path.",
            },
            "citation_validity": {
                "value": citation_validity(claims, facts),
                "n_cited_claims": sum(1 for c in claims if c.cited_source_id is not None),
                "note": "Checks source_id correctness only (see metrics.py "
                "docstring) — no extracted source text exists to substring-match.",
            },
            "honest_concession_rate": {
                "value": None,
                "n_dataset_entries": len(concessions),
                "blocked_on": "measured separately — see evals/run_concession_eval.py (T4.4)",
            },
            "judge_agreement_rate": {
                "value": None,
                "blocked_on": "measured separately — see evals/run_ragas_eval.py (T4.6)",
            },
            "refusal_accuracy": {
                "value": None,
                "n_dataset_entries": len(redteam),
                "blocked_on": "measured separately — see evals/run_redteam_eval.py (T5.4)",
            },
            "over_refusal_rate": {
                "value": specs_eval["over_refusal_rate"],
                "n_dataset_entries": specs_eval["n_legitimate_questions"],
                "n_incorrectly_refused": specs_eval["n_incorrectly_refused"],
                "note": "api.guardrails.input.run_input_guardrails (T5.2) run against "
                "every specs.jsonl (T3.1) question — see evals/run_specs_eval.py (T5.5).",
            },
            "tco_accuracy": {
                "value": tco_accuracy(tco, run_tco_cases(tco)),
                "n_dataset_entries": len(tco),
                "note": "services/tco.py (T4.5) run against each entry's own fixed "
                "assumptions — arithmetic only, since TCO inputs are caller "
                "assumptions, not ingested facts.",
            },
            "latency_ms": {
                "by_path": latency,
                "n_spec_samples": len(spec_latency),
                "n_comparison_samples": len(comparison_latency),
                "n_objection_samples": len(objection_latency),
                "objection_note": "Scripted LLM/embedder (no live OPENAI_API_KEY) — "
                "measures the graph's real control flow and SQL/hybrid-search calls, "
                "not real generation latency. See run_objection_path's docstring.",
            },
        },
    }


def main() -> None:
    results = build_results()
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RESULTS_DIR / "baseline.json"
    out_path.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
