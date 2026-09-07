"""evals/run_concession_eval.py — the honest-concession rate (T4.4).

docs/RETRIEVAL.md, Layer 2 custom metrics: "Honest-concession rate — on the
20 cases where the customer is right." This runs `generate_response` +
`check_concession` (api/objection/verify.py) against every
`customer_is_correct: true` entry in `evals/dataset/concessions.jsonl` and
reports the fraction whose response satisfies `GUARDRAILS.md`'s
`must_concede` shape (acknowledge, cite the figure when one is grounded,
give real framing rather than a bare deflection).

Negative-control entries (`customer_is_correct: false`, e.g. conc_009,
conc_020) are deliberately excluded from this rate — `check_concession` only
checks that *retrieved* facts are reflected in the response, it cannot judge
whether the objection's premise itself was true, so scoring it against
negative controls would penalise a response for correctly declining to
concede a false premise. That is exactly the scope docs/RETRIEVAL.md's own
metric definition draws ("the cases where the customer is right").

No live `OPENAI_API_KEY` is guaranteed in this sandbox. Without one, this
runs against `_ScriptedConcessionLLM`, a deterministic proxy that echoes the
retrieved facts into a compliant three-block response — it exercises the
harness (prompt building, response parsing, `check_concession`'s logic)
honestly, but a 100% rate from it measures "the proxy always complies with
its own template," not real generation quality. Re-run with a real key for a
number worth citing.

Usage: `python -m evals.run_concession_eval` (writes
`evals/results/concession_baseline.json`).
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from api.llm.client import CompletionResult, LLMClient, Message
from api.objection.generate import generate_response
from api.objection.state import RetrievedFact
from api.objection.verify import check_concession

DATASET_PATH = Path(__file__).parent / "dataset" / "concessions.jsonl"
RESULTS_DIR = Path(__file__).parent / "results"

_FACTS_SECTION_RE = re.compile(r"Facts:\n(?P<body>.*?)\n\nDocument excerpts:", re.DOTALL)
_FACT_LINE_RE = re.compile(r"^- (.*?) \(source_id=\d+\)$", re.MULTILINE)


class _ScriptedConcessionLLM:
    """Deterministic stand-in for `LLMClient` when no `OPENAI_API_KEY` is
    set — the concession-eval equivalent of `run_retrieval_eval.py`'s
    `_HashEmbedder`/`_LexicalOverlapLLM`. Parses the exact prompt format
    `generate._build_user_prompt` produces and echoes the retrieved facts
    into a response shaped to satisfy `must_concede`, so the harness around
    it (parsing, `check_concession`) is exercised for real, only the
    generation judgment itself is a scripted stand-in.
    """

    def complete(self, messages: list[Message], **_kwargs: Any) -> CompletionResult:
        prompt = messages[0].content
        match = _FACTS_SECTION_RE.search(prompt)
        fact_lines = _FACT_LINE_RE.findall(match.group("body")) if match else []

        if fact_lines:
            what_is_true = "That's a fair point — " + "; ".join(fact_lines) + "."
        else:
            what_is_true = (
                "That's a fair point — we don't have specific sourced figures on "
                "this, but the underlying concern is a real one worth addressing."
            )

        text = (
            f"WHAT'S TRUE: {what_is_true}\n"
            "HOW TO FRAME IT: Acknowledge the gap honestly, then pivot to what "
            "Volvo does offer.\n"
            "WHAT NOT TO CLAIM: Don't promise anything beyond what's stated above."
        )
        return CompletionResult(
            text=text,
            model="scripted-concession-proxy",
            input_tokens=0,
            output_tokens=0,
            cost_usd=None,
            latency_ms=0.0,
            retries=0,
        )


def _load_dataset() -> list[dict[str, Any]]:
    with DATASET_PATH.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def run_concession_eval() -> dict[str, Any]:
    have_openai_key = bool(os.environ.get("OPENAI_API_KEY"))
    llm: LLMClient | _ScriptedConcessionLLM = (
        LLMClient() if have_openai_key else _ScriptedConcessionLLM()
    )

    entries = [e for e in _load_dataset() if e["customer_is_correct"]]

    per_entry: list[dict[str, Any]] = []
    for entry in entries:
        facts = [
            RetrievedFact(claim=fact["claim"], source_id=i)
            for i, fact in enumerate(entry["grounding_facts"])
        ]
        response = generate_response(llm, entry["objection"], facts, [])  # type: ignore[arg-type]
        violations = check_concession(entry["category"], facts, response)
        per_entry.append(
            {"id": entry["id"], "category": entry["category"], "violations": violations}
        )

    n = len(per_entry)
    n_compliant = sum(1 for e in per_entry if not e["violations"])

    return {
        "n_customer_is_right_cases": n,
        "generator": (
            "openai:gpt-4o"
            if have_openai_key
            else "scripted-concession-proxy (OPENAI_API_KEY unset — NOT a measurement of "
            "real generation quality, see module docstring)"
        ),
        "honest_concession_rate": n_compliant / n,
        "per_entry": per_entry,
    }


def main() -> None:
    results = run_concession_eval()
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RESULTS_DIR / "concession_baseline.json"
    out_path.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
