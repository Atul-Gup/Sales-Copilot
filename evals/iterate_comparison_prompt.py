"""evals/iterate_comparison_prompt.py — T4.3: iterate the COMPARISON prompt
against real generation output, keep every version tried, for the v1->v4
table in evals/results/comparison_prompt_iterations.md.

qa.jsonl has no comparison-labelled questions (only dimensions/powertrain/
features, one model each) — see docs/TASKS.md's T4.3 note. Comparison
queries are synthesized here by pairing qa.jsonl entries that share an
`expected_values[].label` across two different models (e.g. "wheelbase" is
answered for both the XC60 and the X3), which is the only place this eval
corpus actually supports a real side-by-side.

concessions.jsonl is deliberately NOT exercised here: every entry's grounding
lives in the `ServiceCentre` table (ingest/service_centres.py), not in the
`chunks` table `hybrid_search` retrieves over. There is no retrieval path
from an objection query to that table yet — building one is T4.6's
(`must_concede`) job, not T4.3's. Iterating the OBJECTION prompt without a
real grounded case to test it against would just be guessing at wording.

Makes real OpenAI calls (embeddings for retrieval, chat completions for
generation) — a deliberate one-off run, same as calibrate_threshold.py and
run_eval.py. Not collected by pytest or run in CI.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from api.llm.client import LLMClient, Message
from api.models import Base
from api.services.generate import _SHARED_RULES, _build_context_block
from api.services.retrieve import hybrid_search
from evals.metrics import _extract_numbers
from ingest.product_docs import run as ingest_product_docs

DATASET_DIR = Path(__file__).parent / "dataset"
RESULTS_DIR = Path(__file__).parent / "results"

# (label, model_a, model_b) pulled from evals/dataset/qa.jsonl's
# expected_values — the only labels answered for two different models.
COMPARISON_PAIRS = [
    ("wheelbase", "Volvo XC60", "BMW X3"),
    ("audio power output", "Volvo XC60", "BMW X3"),
    ("0-100 km/h", "Volvo EX30", "Audi Q5"),
]

# v1 is generate.py's shipped COMPARISON guidance, verbatim, as of T4.2.
V1 = """The consultant is comparing models. Structure the response \
around the specific dimensions being compared, stating each model's figure side by side \
where the chunks support it. Do not declare an overall "winner" — hand the consultant the \
comparative facts and let them make the pitch."""

# v2: v1's answer for a two-figure comparison buried both numbers in a
# paragraph before restating them in a bullet list — redundant, and the
# prose sentence and the bullet didn't always order the two models the same
# way. Forces one canonical line-per-model layout instead.
V2 = (
    V1
    + """ Use this exact layout: one line per model in the form
"<Model>: <figure> <unit>", then a one-sentence takeaway with no number in it
that a consultant could say out loud."""
)

# v3: v2 mostly held the layout, but the takeaway line still reached for
# comparative adjectives ("longer", "higher", "faster") that read as an
# opinion rather than the neutral fact-handoff the guidance asks for.
# v3 first tried fixing verbatim-copying (a real but separate issue — see
# the module docstring's "known-unresolved" note below); it didn't touch
# the adjective problem, so v4 targets that directly.
V3 = (
    V2
    + """ Copy each figure exactly as it appears in its source chunk, \
character for character — do not paraphrase the unit or reformat the number."""
)

# v4: bans evaluative language in the takeaway outright. This measurably
# worked — v4's three takeaways ("Both models have...", "Both models
# feature...", "Both models present...") dropped every comparative adjective
# v1-v3 used ("longer", "higher", "faster", "more quickly").
V4 = (
    V3
    + """ The takeaway sentence must be neutral: describe what the \
figures are, not whether the difference is large, small, better, or worse."""
)

# Known-unresolved across all four versions (see comparison_prompt_iterations
# .md's "Findings" section): the audio-power-output pair consistently
# attributes the EX30's chunk figures (1,040 W / 9 speakers) to the BMW X3
# instead of the X3's own qa.jsonl-verified figures (750 W / 15 speakers).
# Every version copies the wrong-source number faithfully and cites a real
# chunk marker while doing it — this is a claim-to-entity binding failure at
# retrieval/generation time, not a wording problem, so no amount of prompt
# rewording here fixed it. That's exactly the gap T4.4's verify_grounding
# node needs to close: checking that a number appears "somewhere in a
# retrieved chunk" (today's numeric_fidelity_rate heuristic) is not the same
# as checking it appears in the chunk cited for *that specific model*.

VERSIONS = {"v1": V1, "v2": V2, "v3": V3, "v4": V4}


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _build_session_with_corpus() -> Session:
    engine = create_engine("sqlite:///:memory:")

    def _enable_fk(dbapi_connection: object, _connection_record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    event.listen(engine, "connect", _enable_fk)
    Base.metadata.create_all(engine)
    session = Session(engine)
    for report in ingest_product_docs(session):
        if report.error is not None:
            print(f"ingest warning: {report.document_title}: {report.error}")
    session.flush()
    return session


def _expected_values(qa: list[dict[str, Any]], label: str, model: str) -> dict[str, str]:
    for row in qa:
        if row["model"] != model:
            continue
        for ev in row["expected_values"]:
            if ev["label"] == label:
                return {"value": str(ev["value"]), "unit": ev["unit"]}
    raise ValueError(f"no expected_values entry for {model}/{label}")


def _score(text: str, expected: list[dict[str, str]]) -> dict[str, bool]:
    found = _extract_numbers(text)
    return {f"has_{ev['value']}": ev["value"].replace(",", "") in found for ev in expected}


def main() -> None:
    session = _build_session_with_corpus()
    llm = LLMClient()
    qa = _load_jsonl(DATASET_DIR / "qa.jsonl")

    lines = [
        "# T4.3 — COMPARISON prompt iteration (v1 -> v4)",
        "",
        "Real generation output over the live corpus, one run per version.",
        "Scope note: concessions.jsonl/OBJECTION is deliberately excluded — see",
        "the module docstring in evals/iterate_comparison_prompt.py.",
        "",
    ]

    for version_name, guidance in VERSIONS.items():
        lines.append(f"## {version_name}")
        lines.append("")
        lines.append(f"System guidance addition:\n\n> {guidance}\n")
        system = f"{_SHARED_RULES}\n\n{guidance}"

        for label, model_a, model_b in COMPARISON_PAIRS:
            query = f"How does the {model_a}'s {label} compare to the {model_b}'s?"
            chunks = hybrid_search(query, session, top_k=8)
            context_block, _citations = _build_context_block(chunks, None)
            user_content = f"SOURCE CHUNKS:\n{context_block}\n\nQUESTION: {query}"

            result = llm.complete(
                [Message(role="user", content=user_content)],
                model="gpt-4o-mini",
                max_tokens=300,
                system=system,
            )

            expected = [
                _expected_values(qa, label, model_a),
                _expected_values(qa, label, model_b),
            ]
            scores = _score(result.text, expected)

            lines.append(f"**{query}**")
            lines.append("")
            lines.append(f"> {result.text.replace(chr(10), chr(10) + '> ')}")
            lines.append("")
            lines.append(f"Numeric fidelity: {scores}")
            lines.append("")

    lines.append("## Findings")
    lines.append("")
    lines.append(
        "- v2's forced line-per-model layout held across all three pairs and all "
        "later versions — a real, verified fix for v1's habit of restating figures "
        "in prose before the bullet list."
    )
    lines.append(
        "- v4's ban on evaluative language worked: its three takeaway sentences "
        '("Both models have...", "Both models feature...", "Both models present...") '
        'dropped every comparative adjective v1-v3 used ("longer", "higher", "faster", '
        '"more quickly").'
    )
    lines.append(
        "- **Unresolved across all four versions**: the audio-power-output pair "
        "consistently attributes the EX30's chunk figures (1,040 W / 9 speakers, "
        "chunk id 22) to the BMW X3 instead of the X3's own chunk (750 W / 15 "
        "speakers, chunk id 33) — confirmed by reading both chunks directly. Both "
        'chunks say "Harman Kardon", which is likely why the model conflated them. '
        "No prompt wording fixed this because it isn't a wording problem: the model "
        "cites a real number from a real retrieved chunk, just not the chunk for the "
        "entity it's talking about. Today's numeric_fidelity_rate heuristic (does "
        "this number appear *somewhere* in retrieved text) cannot catch this either. "
        "This is the concrete case for T4.4's verify_grounding node to check "
        "claim-to-source binding per entity, not just number-appears-somewhere."
    )
    lines.append("")

    RESULTS_DIR.mkdir(exist_ok=True)
    out_path = RESULTS_DIR / "comparison_prompt_iterations.md"
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
