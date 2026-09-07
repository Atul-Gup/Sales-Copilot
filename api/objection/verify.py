"""api/objection/verify.py — verify_grounding node (T4.4).

Two checks, folded into one violation list so the graph only needs one
branch point:

1. Grounding — every claim in the generated response's WHAT'S TRUE section
   must trace back to something in the retrieved facts or chunks. Claim
   extraction was originally (T4.4) a structured LLM call
   (docs/RETRIEVAL.md: "Extract atomic claims from the generated response,
   a structured LLM call"). T6.4 replaced it with `extract_claims_deterministic`,
   a plain sentence split — the same sentence-level granularity
   `evals/ragas_metrics.py`'s `faithfulness` proxy already uses for the same
   reason: this node runs on every single generation including the retry,
   so docs/TASKS.md's "optimise the objection path" target made the extra
   sequential LLM round-trip (verify_grounding was previously
   generate -> [claim-extraction call] -> grounding-check on every attempt)
   the first thing worth cutting. Trade-off, documented rather than hidden:
   a compound sentence covering two facts, one grounded and one not, is now
   judged as a single claim instead of two — coarser than what an LLM-based
   extractor could do, and a real regression in that one respect, accepted
   because removing an entire network round-trip on the request's critical
   path was judged the larger win (see docs/TASKS.md's T6.4 entry for the
   full "what worked / what didn't" writeup). Matching each claim against
   the retrieved context is, as before, a deterministic lexical-overlap
   check rather than an embedding-similarity call — still a real limitation
   on its own (a claim can be worded well enough to dodge overlap, or share
   words with unrelated context), documented here rather than hidden.
2. `must_concede` (GUARDRAILS.md) — a known-weakness category must have its
   retrieved facts reflected in the response: acknowledged, and cited when
   present. This heuristic only checks that the facts *retrieved* for this
   turn show up in the response; it cannot tell on its own whether the
   customer's underlying claim was actually correct (conc_020-style negative
   controls, where the retrieved fact **contradicts** the objection, need the
   response to state that contradiction, not "acknowledge" it) — this
   distinction is why evals/run_concession_eval.py scopes its reported rate
   to the customer-is-right cases only, matching docs/RETRIEVAL.md's Layer 2
   metric definition ("the 20 cases where the customer is right").
"""

from __future__ import annotations

import re

from api.objection.state import GeneratedResponse, RetrievedChunk, RetrievedFact

KNOWN_WEAKNESS_CATEGORIES = frozenset(
    {
        "service_network",
        "price_positioning",
        "resale_value",
        "brand_prestige",
        "waiting_period",
    }
)

GROUNDING_OVERLAP_THRESHOLD = 0.5

_STOPWORDS = frozenset(
    "a an the is are was were be been being to of in on at for and or but with "
    "this that these those it its as by from not no does do has have".split()
)

_ACKNOWLEDGE_RE = re.compile(
    r"\b(you'?re right|that'?s (true|correct|fair)|fair point|acknowledg|"
    r"it'?s true|correctly (says?|notes?)|indeed|is a real|does have fewer|"
    r"is limited|does lag|is smaller|gap|fewer than|less than)\b",
    re.IGNORECASE,
)

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def _tokenize(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    # The `len(w) > 2` filter is meant to drop short noise words, but it was
    # also silently dropping short numeric tokens ("11", "12", "60", "3") —
    # exactly the figures grounding exists to check. A generated claim
    # restating a real retrieved "11.2 in" display size was failing
    # grounding for lack of overlap on the one token (`11`) that mattered.
    # Digits are kept regardless of length; short words are still filtered.
    return {w for w in words if w not in _STOPWORDS and (len(w) > 2 or w.isdigit())}


def extract_claims_deterministic(text: str) -> list[str]:
    """One claim per sentence in `text` — T6.4's replacement for the T4.4
    LLM-based `extract_claims` (removed; see module docstring for why and
    the trade-off it accepts). Never fails: unlike an LLM call, there is no
    network error or unparseable-response case to handle, which is also why
    `verify_grounding` no longer has a `claim_extraction_failed` violation.
    """
    stripped = text.strip()
    if not stripped:
        return []
    return [s.strip() for s in _SENTENCE_SPLIT_RE.split(stripped) if s.strip()]


def _is_grounded(claim: str, context_tokens: set[str]) -> bool:
    claim_tokens = _tokenize(claim)
    if not claim_tokens:
        return True
    overlap = claim_tokens & context_tokens
    if len(overlap) / len(claim_tokens) >= GROUNDING_OVERLAP_THRESHOLD:
        return True
    # A real GPT-generated sentence citing several genuinely retrieved
    # figures in verbose prose ("Additionally, the XC60 boasts significant
    # ground clearance at 211 mm, which is beneficial for...") can dilute
    # the word-overlap ratio below threshold on filler words alone, even
    # though every number in it is real — found streaming a live comparison
    # in production (T7.4). The actual risk this check exists to catch is
    # an invented figure, not verbose framing around real ones: if every
    # digit the claim cites is present in the retrieved context, the claim
    # is grounded regardless of the prose-word overlap ratio. A claim citing
    # even one number NOT in context still falls through to the ratio
    # result above — this cannot admit a hallucinated figure, only forgive
    # wordiness around real ones.
    claim_numbers = {t for t in claim_tokens if t.isdigit()}
    return bool(claim_numbers) and claim_numbers <= context_tokens


def check_grounding(
    claims: list[str], facts: list[RetrievedFact], chunks: list[RetrievedChunk]
) -> list[str]:
    context_tokens = _tokenize(
        " ".join(fact.claim for fact in facts) + " " + " ".join(chunk.text for chunk in chunks)
    )
    return [
        f"unsupported_claim: {claim}" for claim in claims if not _is_grounded(claim, context_tokens)
    ]


def check_concession(
    category: str, facts: list[RetrievedFact], response: GeneratedResponse
) -> list[str]:
    if category not in KNOWN_WEAKNESS_CATEGORIES:
        return []

    combined_text = f"{response.what_is_true} {response.how_to_frame_it}"

    violations = []
    if not _ACKNOWLEDGE_RE.search(combined_text):
        violations.append("must_concede: response does not acknowledge the known weakness")

    if facts:
        fact_tokens = _tokenize(" ".join(fact.claim for fact in facts))
        response_tokens = _tokenize(combined_text)
        if not (fact_tokens & response_tokens):
            violations.append("must_concede: response does not cite the retrieved figure")

    if not response.how_to_frame_it.strip():
        violations.append("must_concede: response gives no framing, only a deflection")

    return violations


def verify_grounding(
    category: str,
    facts: list[RetrievedFact],
    chunks: list[RetrievedChunk],
    response: GeneratedResponse,
) -> list[str]:
    claims = extract_claims_deterministic(response.what_is_true)
    violations = check_grounding(claims, facts, chunks)
    violations.extend(check_concession(category, facts, response))
    return violations
