"""api/guardrails/input.py — input guardrails: injection stripping, scope
check, customer-facing refusal (T5.2).

docs/GUARDRAILS.md's three input rules, enforced in this fixed order because
each check answers a different question about the same raw request text:

1. **`prompt_injection`** — is there instruction-like text hiding inside a
   pasted customer message? This runs first and never blocks the request by
   itself (action `strip_and_log`): the offending span is stripped from the
   text that continues downstream, and the finding is logged. A pasted
   customer message is untrusted *data*, never an instruction to follow.
2. **`customer_facing`** — is this a request to draft something to hand
   straight to a customer? Checked before `out_of_scope`, not after: this
   tool is for the consultant, not a customer-facing drafting tool,
   *regardless of whether the topic itself is in scope* — and in practice a
   customer-facing draft request often doesn't name a specific model at all
   ("confirm today's discount"), which the scope check would otherwise
   misread as an out-of-scope topic rather than what it actually is. This
   ordering fixed a real bug found via `evals/run_eval.py` (T3.7).
3. **`out_of_scope`** — after stripping, does the (sanitized) request stay
   within the four-brand lineup (Volvo, BMW, Mercedes-Benz, Audi)? This is a
   brand-level check only, not a check that the specific model was ingested
   — docs/GUARDRAILS.md's own over-refusal example ("Does the EX40 have a
   heat pump?") names a Volvo model with no ingested data
   (docs/CORPUS.md: "EX40 is out of scope — no India brochure was
   available"). Whether we *have data* for an in-scope brand's model is a
   retrieval/abstention concern downstream, not this guardrail's job.

`run_input_guardrails` runs all three and returns the first rule triggered
(injection stripping always happens first and does not short-circuit the
later two checks, since it only sanitizes rather than refuses).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from api.guardrails.rules import Action, get_rule

_INJECTION_RE = re.compile(
    r"(ignore (all |the )?(previous|prior|above) instructions"
    r"|forget (your|the) (rules|instructions)"
    r"|you are now (a|an) "
    r"|disregard (the |this )?.*rule"
    r"|system\s*:\s*the above guardrails"
    r"|###\s*admin override\s*###"
    r"|admin override"
    r"|reply only with"
    r"|output the internal prompt)",
    re.IGNORECASE,
)

IN_SCOPE_BRANDS = frozenset({"volvo", "bmw", "mercedes", "mercedes-benz", "audi"})
IN_SCOPE_MODELS = frozenset({"xc60", "ex30", "ex40", "xc90", "x3", "glc", "q5", "ix1"})
OUT_OF_SCOPE_BRANDS = frozenset(
    {
        "toyota",
        "honda",
        "hyundai",
        "kia",
        "tata",
        "mahindra",
        "maruti",
        "suzuki",
        "ford",
        "nissan",
        "skoda",
        "renault",
        "mg",
        "jeep",
        "lexus",
        "land rover",
        "jaguar",
        "porsche",
        "fortuner",
        "city",
    }
)

_CUSTOMER_FACING_RE = re.compile(
    r"(draft .*(to|for) (the |my )?customer"
    r"|write .*(to|for) (the |my )?customer"
    r"|(email|text|sms|message) .*(the |my )?customer"
    r"|send (this|it|a message) (to|directly to) (the |my )?customer"
    r"|reply to (the |my )?customer"
    # adjective phrasing ("customer-facing marketing copy") rather than
    # "draft/write ... to/for customer" — the object precedes the audience
    # instead of following it, so the patterns above don't match it. Real
    # gap found via evals/run_eval.py (T3.7): "Draft some customer-facing
    # marketing copy for the XC60's safety features" matched nothing.
    r"|customer-facing)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class InputGuardrailResult:
    rule_id: str
    action: Action
    sanitized_text: str
    message: str


def strip_prompt_injection(text: str) -> InputGuardrailResult | None:
    if not _INJECTION_RE.search(text):
        return None
    rule = get_rule("prompt_injection")
    sanitized = _INJECTION_RE.sub("[instruction-like text removed]", text)
    return InputGuardrailResult(
        rule_id=rule.id,
        action=rule.action,
        sanitized_text=sanitized,
        message=(
            "Instruction-like text inside the pasted customer message was "
            "stripped and logged. It is treated as data, not as an "
            "instruction to follow."
        ),
    )


def _mentions_any(text_lower: str, terms: frozenset[str]) -> bool:
    return any(re.search(rf"\b{re.escape(term)}\b", text_lower) for term in terms)


def check_out_of_scope(text: str) -> InputGuardrailResult | None:
    text_lower = text.lower()
    in_scope = _mentions_any(text_lower, IN_SCOPE_BRANDS) or _mentions_any(
        text_lower, IN_SCOPE_MODELS
    )
    out_of_scope_brand = _mentions_any(text_lower, OUT_OF_SCOPE_BRANDS)
    if out_of_scope_brand or not in_scope:
        rule = get_rule("out_of_scope")
        return InputGuardrailResult(
            rule_id=rule.id,
            action=rule.action,
            sanitized_text=text,
            message=(
                "This tool only has grounded data for the Volvo lineup and "
                "its BMW, Mercedes-Benz, and Audi competitor set — this "
                "question falls outside that scope."
            ),
        )
    return None


def check_customer_facing(text: str) -> InputGuardrailResult | None:
    if not _CUSTOMER_FACING_RE.search(text):
        return None
    rule = get_rule("customer_facing")
    return InputGuardrailResult(
        rule_id=rule.id,
        action=rule.action,
        sanitized_text=text,
        message=(
            "This is an internal consultant tool, not a customer-facing "
            "drafting tool — it won't produce something to send directly "
            "to a customer."
        ),
    )


def run_input_guardrails(text: str) -> tuple[InputGuardrailResult | None, str]:
    """Run all three input checks. Returns (blocking_result, sanitized_text).

    `blocking_result` is the `out_of_scope` or `customer_facing` result if
    either fired (a request that should not proceed), else None. The
    returned text has any prompt-injection span already stripped regardless
    of whether a blocking rule also fired, so a logged/stripped injection is
    never lost even inside an otherwise-blocked request.
    """
    injection = strip_prompt_injection(text)
    sanitized = injection.sanitized_text if injection is not None else text

    # customer_facing is checked before out_of_scope, not after: a request
    # to draft something for a customer is a violation "regardless of
    # whether the topic itself is in scope" (see module docstring) — and in
    # practice, a customer-facing draft request often doesn't name a
    # specific model at all ("confirm today's discount"), which would
    # otherwise make it look like a scope violation instead of what it
    # actually is. Real bug this order fixes, found via evals/run_eval.py
    # (T3.7): "Write an email to send the customer confirming today's
    # discount" was previously misreported as out_of_scope.
    customer_facing_violation = check_customer_facing(sanitized)
    if customer_facing_violation is not None:
        return customer_facing_violation, sanitized

    scope_violation = check_out_of_scope(sanitized)
    if scope_violation is not None:
        return scope_violation, sanitized

    return None, sanitized
