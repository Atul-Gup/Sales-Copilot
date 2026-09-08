"""Query classification: SPEC, COMPARISON, or OBJECTION.

Rule-based, not a model — there is no `llm/client.py` yet (see T4.1), and a
regex pass over the query text comfortably clears the <100ms budget from
docs/ARCHITECTURE.md without adding an LLM call just to decide which prompt
to use. Per docs/RETRIEVAL.md's "single generation path" decision, every
intent class now goes through full LLM narration over the retrieved chunks —
this classifier only selects which prompt style generation uses downstream.
It never skips retrieval and never decides whether generation happens.

Precedence matters: OBJECTION markers are checked first because an objection
often *contains* a comparison ("BMW gives free service, why doesn't Volvo")
or a spec-shaped clause, but the customer sentiment is the part that needs
handling. COMPARISON is checked next (explicit vs./compare wording, or two+
brand/model mentions). Everything else defaults to SPEC, since a plain
factual question is the common case and has no distinguishing marker of
its own.
"""

import re
from enum import StrEnum

_BRANDS = ["volvo", "bmw", "mercedes", "mercedes-benz", "merc", "audi"]
_MODELS = [
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
]

_OBJECTION_PATTERNS = [
    r"\bbut\b",
    r"\bheard (that|from)\b",
    r"\bfriend (told|said|has)\b",
    r"\bwhy (should|would|does|is)\b",
    r"\bisn'?t it true\b",
    r"\bworried?\b",
    r"\bconcerned?\b",
    r"\bcheaper (than|at)\b",
    r"\bresale\b",
    r"\bi can get\b",
    r"\bmy neighbou?r\b",
    r"\bnot as good as\b",
    r"\bwaiting period\b",
    r"\bservice network\b",
    r"\bcustomer says\b",
    r"\bconvince me\b",
]

_COMPARISON_PATTERNS = [
    r"\bvs\.?\b",
    r"\bversus\b",
    r"\bcompare[d]?\b",
    r"\bcomparison\b",
    r"\bdifference between\b",
    r"\bbetter than\b",
    r"\bwhich (is|one is|has)\b",
]


class QueryType(StrEnum):
    SPEC = "SPEC"
    COMPARISON = "COMPARISON"
    OBJECTION = "OBJECTION"


def _matches_any(patterns: list[str], text: str) -> bool:
    return any(re.search(p, text) for p in patterns)


_MODEL_SPACING_RE = re.compile(r"(?<=[a-z])\s+(?=\d)")


def normalize_model_spacing(text: str) -> str:
    """Collapse a space between a model's letter prefix and its digits
    ("ex 30" -> "ex30", "xc 60" -> "xc60") so matching is robust to how a
    consultant naturally types it — a real user report ("What is power of
    ex 30" was wrongly refused as out-of-scope) found this gap. Used here
    and in `api/guardrails/input.py::check_out_of_scope` before any
    brand/model regex match.
    """
    return _MODEL_SPACING_RE.sub("", text)


def mentioned_entities(text: str) -> set[str]:
    """Public: also used by `api/services/pipeline.py::refuse_gracefully`
    to name what's missing rather than refusing silently."""
    normalized = normalize_model_spacing(text)
    return {
        name for name in (*_BRANDS, *_MODELS) if re.search(rf"\b{re.escape(name)}\b", normalized)
    }


def classify(query: str) -> QueryType:
    """Classify a consultant's query as SPEC, COMPARISON, or OBJECTION.

    Pure regex/keyword matching — no LLM call, no I/O. Runs in well under
    the 100ms budget in docs/ARCHITECTURE.md.
    """
    text = query.lower().strip()

    if _matches_any(_OBJECTION_PATTERNS, text):
        return QueryType.OBJECTION

    if _matches_any(_COMPARISON_PATTERNS, text) or len(mentioned_entities(text)) >= 2:
        return QueryType.COMPARISON

    return QueryType.SPEC
