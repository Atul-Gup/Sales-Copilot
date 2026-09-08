"""evals/metrics.py — the scoring functions behind every metric in
docs/PRD.md §6 and docs/RETRIEVAL.md's evals table (T3.5).

Built ahead of generation (Phase 4 doesn't exist yet) on purpose — per
docs/TASKS.md's Phase 3 banner, "build the ruler before tuning generation."
Every function here takes plain data (strings, chunk texts, bools) rather
than a pipeline object, so it can be unit-tested against synthetic examples
now and wired into `evals/run_eval.py` (T3.7) against real pipeline output
later, unchanged.

Two functions are explicitly heuristic and say so in their docstring:
`numeric_fidelity_rate` and `citation_validity_rate` do substring/overlap
matching rather than real claim-to-source entailment. That's an honest
placeholder, not a finished NLP solution — docs/RETRIEVAL.md already commits
to validating the RAGAS layer against 30 hand-labelled examples for the same
reason (LLM-judged and heuristic scores are both noisy until checked against
a human). Revisit these two once T4.4's real grounding-check logic exists;
until then this is the closest honest proxy without fabricating a more
sophisticated-sounding metric that isn't actually implemented.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

_TOKEN_RE = re.compile(r"[\w.,]+")
_PURE_NUMBER_RE = re.compile(r"\d[\d,]*\.?\d*")


def _extract_numbers(text: str) -> set[str]:
    """Whole-token digit runs only (e.g. "2865", "1,410") — tokenizing
    first, rather than matching digits inline, keeps a model name like
    "XC60" or "xDrive20d" from contributing a spurious "60" or "20".
    """
    numbers = set()
    for token in _TOKEN_RE.findall(text):
        cleaned = token.strip(".,")
        if cleaned and _PURE_NUMBER_RE.fullmatch(cleaned):
            numbers.add(cleaned.replace(",", ""))
    return numbers


def numeric_fidelity_rate(response_text: str, expected_values: list[dict[str, Any]]) -> float:
    """Fraction of `expected_values` (each a {value, unit, label} dict, per
    evals/dataset/qa.jsonl) whose exact numeric value appears somewhere in
    `response_text`.

    Heuristic, not claim-level entailment: this checks that the correct
    number was stated at least once, not that it was attached to the right
    label when multiple similar numbers are present. A response with no
    expected values scores 1.0 (vacuously correct — nothing to check).
    """
    if not expected_values:
        return 1.0
    found = _extract_numbers(response_text)
    correct = sum(1 for ev in expected_values if str(ev["value"]).replace(",", "") in found)
    return correct / len(expected_values)


def citation_validity_rate(citations: list[tuple[str, str]]) -> float:
    """Fraction of (claim, cited_chunk_text) pairs where the claim's stated
    numbers (if any) actually appear in the chunk it was cited against, and
    the claim shares at least one non-trivial word with the chunk otherwise.

    Heuristic overlap check, not semantic entailment — see module docstring.
    An empty citation list scores 1.0 (nothing cited, nothing invalid).
    """
    if not citations:
        return 1.0
    valid = 0
    for claim, chunk_text in citations:
        claim_numbers = _extract_numbers(claim)
        chunk_numbers = _extract_numbers(chunk_text)
        if claim_numbers:
            if claim_numbers.issubset(chunk_numbers):
                valid += 1
            continue
        claim_words = {w.lower() for w in re.findall(r"[a-zA-Z]{4,}", claim)}
        chunk_words = {w.lower() for w in re.findall(r"[a-zA-Z]{4,}", chunk_text)}
        if claim_words & chunk_words:
            valid += 1
    return valid / len(citations)


def hallucinated_fact_rate(claims: list[str], retrieved_texts: list[str]) -> float:
    """Fraction of `claims` whose numbers (if any) or key words appear in
    none of `retrieved_texts` — i.e. asserted without support in what was
    actually retrieved for the query. An empty claims list scores 0.0 (no
    claims, nothing hallucinated).
    """
    if not claims:
        return 0.0
    combined_numbers = set().union(*(_extract_numbers(t) for t in retrieved_texts)) or set()
    combined_words = (
        set().union(*({w.lower() for w in re.findall(r"[a-zA-Z]{4,}", t)} for t in retrieved_texts))
        or set()
    )
    hallucinated = 0
    for claim in claims:
        claim_numbers = _extract_numbers(claim)
        if claim_numbers:
            if not claim_numbers.issubset(combined_numbers):
                hallucinated += 1
            continue
        claim_words = {w.lower() for w in re.findall(r"[a-zA-Z]{4,}", claim)}
        if not claim_words & combined_words:
            hallucinated += 1
    return hallucinated / len(claims)


def _rate(results: list[bool]) -> float:
    if not results:
        return 0.0
    return sum(results) / len(results)


def in_corpus_recall(answered_correctly: list[bool]) -> float:
    """Of genuinely answerable questions (evals/dataset/qa.jsonl), the
    fraction correctly answered rather than wrongly refused."""
    return _rate(answered_correctly)


def out_of_corpus_refusal_rate(refused_correctly: list[bool]) -> float:
    """Of unanswerable questions (evals/dataset/out_of_corpus.jsonl), the
    fraction correctly refused rather than answered from general knowledge.

    Must always be reported alongside in_corpus_recall — a system that
    refuses everything scores perfectly here and zero there.
    """
    return _rate(refused_correctly)


def honest_concession_rate(conceded_correctly: list[bool]) -> float:
    """Of objections where the customer is factually right
    (evals/dataset/concessions.jsonl), the fraction where the response
    concedes per docs/GUARDRAILS.md's must_concede shape rather than
    deflecting."""
    return _rate(conceded_correctly)


def refusal_accuracy(matched_expected_action: list[bool]) -> float:
    """Of the adversarial set (evals/dataset/redteam.jsonl), the fraction
    where the triggered guardrail action matched the entry's
    expected_action. Report per rule ID, never as one aggregate number, per
    docs/GUARDRAILS.md."""
    return _rate(matched_expected_action)


def over_refusal_rate(incorrectly_refused: list[bool]) -> float:
    """Of genuinely answerable questions (evals/dataset/qa.jsonl), the
    fraction wrongly refused. Must be reported beside refusal_accuracy
    always — over-cautious guardrails are a broken product, not a safe
    one, per docs/GUARDRAILS.md's "Over-refusal" section."""
    return _rate(incorrectly_refused)


@dataclass(frozen=True)
class LatencySample:
    intent: str
    latency_ms: float


def latency_by_intent(samples: list[LatencySample]) -> dict[str, dict[str, float]]:
    """p50/p95/mean latency per intent class (SPEC/COMPARISON/OBJECTION),
    per docs/RETRIEVAL.md's "report per-intent-class latency honestly"
    requirement — a single aggregate hides whether one intent class is
    disproportionately slow."""
    by_intent: dict[str, list[float]] = {}
    for sample in samples:
        by_intent.setdefault(sample.intent, []).append(sample.latency_ms)

    result: dict[str, dict[str, float]] = {}
    for intent, values in by_intent.items():
        ordered = sorted(values)
        result[intent] = {
            "p50": _percentile(ordered, 0.50),
            "p95": _percentile(ordered, 0.95),
            "mean": sum(ordered) / len(ordered),
        }
    return result


def _percentile(sorted_values: list[float], fraction: float) -> float:
    if len(sorted_values) == 1:
        return sorted_values[0]
    index = fraction * (len(sorted_values) - 1)
    lower, upper = int(index), min(int(index) + 1, len(sorted_values) - 1)
    weight = index - lower
    return sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight
