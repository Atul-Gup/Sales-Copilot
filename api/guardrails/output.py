"""api/guardrails/output.py — output guardrails: citation, protocol,
disparagement, service overstatement, price/promise, staleness, and
certainty checks (T5.3).

Covers every `OUTPUT_RULES` (T5.1) entry except `must_concede`, which
`api/services/concede.py` (T4.6) already implements as its own deterministic
path — a known-weakness objection is answered from real structured data
before generation ever runs, so there is no generated text for this module
to check in that case. Every check in this module instead operates on plain
generated response text (plus, where a rule needs it, a small piece of
structured context such as a set of known-covered cities or a staleness
timestamp), so it can run over *any* generated response — SPEC, COMPARISON,
or OBJECTION — not just one intent class's output.

docs/ARCHITECTURE.md: "Output guardrails run after generation and before
the response returns. A violation triggers one regeneration attempt, then
refusal." `run_output_guardrails` returns every violation found in one pass;
the regenerate-once-then-refuse loop is the caller's job — `api/services/
verify.py`'s `verify_grounding` LangGraph cycle (T4.4) is that caller,
folding these violations into the same loop it already uses for numeric
grounding (T5.3).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from api.guardrails.rules import Action, get_rule

_PROTOCOL_TERMS_RE = re.compile(
    r"\b(euro\s*ncap|bharat\s*ncap|bnc ap|global\s*ncap)\b", re.IGNORECASE
)

_COMPETITOR_TERMS = ("bmw", "mercedes", "audi", "x3", "glc", "q5", "ix1")
_COMPARISON_RE = re.compile(r"\b(than|compared to|vs\.?|versus)\b", re.IGNORECASE)
_NUMBER_RE = re.compile(r"\d")
# Prose attribution ("per the spec sheet") is one way a claim can be
# attributed, but `[n]` is the *actual* citation convention every generated
# response uses (generate.py's prompt asks for it, chat.py's
# `_referenced_citations` parses it, verify.py's numeric-grounding check
# relies on it existing) — this regex originally only recognized the prose
# phrasing, so a properly `[n]`-cited comparison with a competitor mention
# and no incidental "based on"/"per the" wording anywhere in the response
# was a false-positive `uncited_claim` violation on every single generation
# attempt, forcing an otherwise-correct answer into a hard refusal after
# the regenerate-once loop ran out (real user report: "in what level xc 60
# is better than x3" refused with a grounding-mismatch message despite every
# number in the draft actually carrying its own `[n]` marker).
_ATTRIBUTION_RE = re.compile(
    r"\b(source|per the|according to|based on|spec sheet|cites?)\b|\[\d+\]", re.IGNORECASE
)

_DISPARAGEMENT_RE = re.compile(
    r"\b(unreliable|worse (brand|than)|worse\b|feels? cheap|badge[- ]engineered junk|"
    r"junk|garbage|a joke|joke compared|gone downhill|inferior|subpar|worst|did badly|"
    r"cheap(ly)? (made|built)|not as good)\b",
    re.IGNORECASE,
)

_BLANKET_COVERAGE_RE = re.compile(
    r"\b(nationwide|pan[- ]india|full(y)? covered|every city|all cities|"
    r"full pan[- ]india coverage|complete coverage)\b",
    re.IGNORECASE,
)
_AFFIRMATIVE_SERVICE_RE = re.compile(
    r"\b(confirm(ed)? (that )?we have|assume .*(will have|have)|just (say|tell)|"
    r"tell (the customer|them) (service|coverage)|say we (have|cover)|"
    r"definitely (has|have|covers))\b.{0,40}\b(service|centre|center|coverage)\b",
    re.IGNORECASE,
)

_ON_ROAD_PRICE_RE = re.compile(r"\bon-road price\b", re.IGNORECASE)
_PRICE_FIGURE_RE = re.compile(r"(₹|rs\.?\s*\d|inr\s*\d|\d[\d,]*\s*lakh)", re.IGNORECASE)
_PRICE_CAVEAT_RE = re.compile(
    r"\b(varies|vary|depends|approx|estimate|indicative|subject to change|"
    r"city[- ]specific|registration)\b",
    re.IGNORECASE,
)

_DELIVERY_PROMISE_RE = re.compile(
    r"\b(will definitely (arrive|be delivered|deliver)|"
    r"(guarantee|promise)[a-z]* (delivery|it will arrive)|"
    r"will arrive (within|before|by)|definitely arrive)\b",
    re.IGNORECASE,
)

_DISCOUNT_PROMISE_RE = re.compile(
    r"\b(we (can|will) (knock off|discount)|will definitely match|"
    r"guarantee[a-z]* (a |the )?discount|finance (will be|is) approved|"
    r"we('ll| will) (match|beat) (the |any )?(discount|price))\b",
    re.IGNORECASE,
)

_CERTAINTY_TOPIC_RE = re.compile(
    r"\b(resale value|total cost of ownership|\btco\b)\b", re.IGNORECASE
)
_CERTAINTY_CLAIM_RE = re.compile(
    r"\b(will (definitely |certainly )?be worth|guaranteed (resale|to retain)|"
    r"will definitely retain|is guaranteed)\b",
    re.IGNORECASE,
)
_CERTAINTY_CAVEAT_RE = re.compile(
    r"\b(estimate|assumption|approx|projection|illustrative|not guaranteed)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class OutputGuardrailViolation:
    rule_id: str
    action: Action
    message: str


def check_uncited_claim(text: str) -> OutputGuardrailViolation | None:
    text_lower = text.lower()
    mentions_competitor = any(term in text_lower for term in _COMPETITOR_TERMS)
    if (
        mentions_competitor
        and _COMPARISON_RE.search(text)
        and _NUMBER_RE.search(text)
        and not _ATTRIBUTION_RE.search(text)
    ):
        rule = get_rule("uncited_claim")
        return OutputGuardrailViolation(
            rule_id=rule.id,
            action=rule.action,
            message="A competitor factual claim with no source attribution is legally exposed.",
        )
    return None


def check_cross_protocol_safety(text: str) -> OutputGuardrailViolation | None:
    protocols = {m.group(0).lower().replace(" ", "") for m in _PROTOCOL_TERMS_RE.finditer(text)}
    normalized = {p.replace("bncap", "bharatncap") for p in protocols}
    if len(normalized) >= 2:
        rule = get_rule("cross_protocol_safety")
        return OutputGuardrailViolation(
            rule_id=rule.id,
            action=rule.action,
            message=(
                "Different safety-rating protocols cannot be compared or "
                "equated directly — refuse rather than answer."
            ),
        )
    return None


def check_disparagement(text: str) -> OutputGuardrailViolation | None:
    if _DISPARAGEMENT_RE.search(text):
        rule = get_rule("disparagement")
        return OutputGuardrailViolation(
            rule_id=rule.id,
            action=rule.action,
            message="State checkable figures, never a subjective characterisation.",
        )
    return None


def check_service_overstatement(
    text: str, known_service_cities: frozenset[str] | None = None
) -> OutputGuardrailViolation | None:
    triggered = bool(_BLANKET_COVERAGE_RE.search(text)) or bool(
        _AFFIRMATIVE_SERVICE_RE.search(text)
    )
    if known_service_cities is not None:
        text_lower = text.lower()
        for city in re.findall(r"\bin ([A-Z][a-z]+)\b", text):
            if city.lower() not in known_service_cities and (
                "service" in text_lower or "centre" in text_lower or "center" in text_lower
            ):
                triggered = True
    if triggered:
        rule = get_rule("service_overstatement")
        return OutputGuardrailViolation(
            rule_id=rule.id,
            action=rule.action,
            message="Never claim service presence beyond what `service_centres` supports.",
        )
    return None


def check_on_road_price(text: str) -> OutputGuardrailViolation | None:
    if (
        _ON_ROAD_PRICE_RE.search(text)
        and _PRICE_FIGURE_RE.search(text)
        and not _PRICE_CAVEAT_RE.search(text)
    ):
        rule = get_rule("on_road_price")
        return OutputGuardrailViolation(
            rule_id=rule.id,
            action=rule.action,
            message="On-road price varies by city registration — never state it as a flat fact.",
        )
    return None


def check_delivery_promise(text: str) -> OutputGuardrailViolation | None:
    if _DELIVERY_PROMISE_RE.search(text):
        rule = get_rule("delivery_promise")
        return OutputGuardrailViolation(
            rule_id=rule.id,
            action=rule.action,
            message="Delivery dates are not the consultant's or the tool's authority to promise.",
        )
    return None


def check_discount_promise(text: str) -> OutputGuardrailViolation | None:
    if _DISCOUNT_PROMISE_RE.search(text):
        rule = get_rule("discount_promise")
        return OutputGuardrailViolation(
            rule_id=rule.id,
            action=rule.action,
            message=(
                "Discounts and finance approval are not the consultant's or the tool's authority."
            ),
        )
    return None


def check_no_clinical_certainty(text: str) -> OutputGuardrailViolation | None:
    if (
        _CERTAINTY_TOPIC_RE.search(text)
        and _CERTAINTY_CLAIM_RE.search(text)
        and not _CERTAINTY_CAVEAT_RE.search(text)
    ):
        rule = get_rule("no_clinical_certainty")
        return OutputGuardrailViolation(
            rule_id=rule.id,
            action=rule.action,
            message="Resale and TCO projections are estimates with assumptions, never guaranteed.",
        )
    return None


def check_stale_data(
    stale_after: datetime, reference_time: datetime
) -> OutputGuardrailViolation | None:
    if reference_time > stale_after:
        rule = get_rule("stale_data")
        return OutputGuardrailViolation(
            rule_id=rule.id,
            action=rule.action,
            message=(
                "The underlying fact is older than its staleness "
                "threshold — refuse rather than serve it."
            ),
        )
    return None


def run_output_guardrails(
    text: str,
    *,
    known_service_cities: frozenset[str] | None = None,
    stale_after: datetime | None = None,
    reference_time: datetime | None = None,
) -> list[OutputGuardrailViolation]:
    """Run every text-based output check plus the staleness check when both
    `stale_after` and `reference_time` are supplied. Order matches
    `OUTPUT_RULES`' table order (T5.1).
    """
    violations: list[OutputGuardrailViolation] = []
    checks = [
        check_uncited_claim(text),
        check_cross_protocol_safety(text),
        check_disparagement(text),
        check_service_overstatement(text, known_service_cities),
        check_on_road_price(text),
        check_delivery_promise(text),
        check_discount_promise(text),
        check_no_clinical_certainty(text),
    ]
    if stale_after is not None and reference_time is not None:
        checks.append(check_stale_data(stale_after, reference_time))
    violations.extend(v for v in checks if v is not None)
    return violations
