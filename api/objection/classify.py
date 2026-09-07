"""api/objection/classify.py — classify_objection node (T4.3).

Maps a free-text customer objection to one of a fixed category set, which
determines both what `retrieve` looks up (docs/RETRIEVAL.md: "this is the
Corpus A retrieval trigger") and, for the five known-weakness categories,
whether T4.4's `must_concede` applies.

Categories:
- The five known-weakness categories from GUARDRAILS.md's `must_concede`
  trigger and evals/dataset/concessions.jsonl: service_network,
  price_positioning, resale_value, brand_prestige, waiting_period.
- spec_comparison — a factual spec/feature/safety-rating question, answered
  from Corpus A (api/services/spec_query.py).
- document_qa — a warranty/service-plan/NCAP-report question, answered from
  Corpus B (api/retrieval/hybrid.py).
- other — doesn't fit any of the above. Always routed to `abstain`
  regardless of confidence (see `graph.py`) — forcing one of the above
  categories here would produce confidently wrong framing, which is exactly
  what docs/RETRIEVAL.md's abstain branch exists to prevent.
"""

from __future__ import annotations

import json
import re

from api.llm.client import LLMClient, LLMError, Message
from api.objection.state import ClassificationResult

CLASSIFY_MODEL = "gpt-4o-mini"

CATEGORIES = (
    "service_network",
    "price_positioning",
    "resale_value",
    "brand_prestige",
    "waiting_period",
    "spec_comparison",
    "document_qa",
    "other",
)

# Below this, classify_objection routes to abstain rather than risk
# confidently wrong framing (docs/RETRIEVAL.md's graph). A hand-picked
# default, not yet tuned against a red-team run — T5.4/T5.5 is where that
# happens, same as every other unvalidated threshold in this project.
CONFIDENCE_THRESHOLD = 0.5

_SYSTEM_PROMPT = (
    "You classify a car sales objection into exactly one category from this "
    f"list: {', '.join(CATEGORIES)}.\n\n"
    "- service_network / price_positioning / resale_value / brand_prestige / "
    "waiting_period: the objection raises one of Volvo's known weaknesses.\n"
    "- spec_comparison: a factual question about specs, features, or safety "
    "ratings.\n"
    "- document_qa: a question about warranty terms, service plans, or the "
    "full text of a Euro NCAP report.\n"
    "- other: anything else, including out-of-scope or unanswerable requests.\n\n"
    'Respond with ONLY JSON: {"category": "...", "confidence": 0.0-1.0}. '
    "No other text."
)

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def _parse(text: str) -> ClassificationResult | None:
    match = _JSON_RE.search(text)
    if match is None:
        return None
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    category = parsed.get("category")
    confidence = parsed.get("confidence")
    if category not in CATEGORIES or not isinstance(confidence, int | float):
        return None
    return ClassificationResult(category=category, confidence=float(confidence))


def classify_objection(llm: LLMClient, objection_text: str) -> ClassificationResult:
    """Classify `objection_text`. Falls open to category="other",
    confidence=0.0 (forces abstain, see `graph.py`) on any LLM error or
    unparseable response — an unclassifiable objection is exactly the case
    abstain exists for, not a reason to crash the graph.
    """
    try:
        completion = llm.complete(
            [Message(role="user", content=objection_text)],
            model=CLASSIFY_MODEL,
            max_tokens=100,
            system=_SYSTEM_PROMPT,
        )
    except LLMError:
        return ClassificationResult(category="other", confidence=0.0)

    result = _parse(completion.text)
    if result is None:
        return ClassificationResult(category="other", confidence=0.0)
    return result
