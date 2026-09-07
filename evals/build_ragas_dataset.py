"""evals/build_ragas_dataset.py — one-off builder for
`evals/dataset/ragas.jsonl` (T4.6), the 30-example hand-labelled set
`run_ragas_eval.py` measures judge agreement against.

Not part of the runtime eval — run once (`python -m evals.build_ragas_dataset`)
to regenerate the committed dataset. Every (question, answer, contexts,
ground_truth) tuple is built from real pipeline pieces, not invented text:

- **Document track** (15 entries): `evals/dataset/retrieval.jsonl`'s real
  queries, run through the actual `hybrid_search` (T4.2b) against the real
  ingested Corpus B (`evals/run_retrieval_eval.py`'s `_HashEmbedder` corpus —
  no API key needed, same as that eval). The "answer" is a plain sentence
  built directly from the top retrieved chunk's own text.
- **Objection track** (15 entries): `evals/dataset/concessions.jsonl`'s real
  objections and `grounding_facts`, run through `generate_response` with a
  scripted proxy LLM (same shape as T4.4's `_ScriptedConcessionLLM`) that
  echoes the retrieved facts into a compliant response.

Each base entry is built clean, then a fixed fraction per track is
deliberately corrupted (an injected unsupported sentence, an irrelevant
context swapped in, or a needed context dropped) so the hand-labelled scores
actually span the 0-1 range — a dataset that is all 1.0s can't validate
whether `ragas_metrics.py` catches a real problem. The corruption is what
determines each entry's `hand_labels`: I assign those by construction (I
know exactly what was injected or removed), which is the same "the person
building the fixture is the one who can correctly label it" logic
`evals/dataset/tco.jsonl`'s hand-computed workings rely on.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import select

from api.models import DocumentChunk
from api.objection.generate import generate_response
from api.objection.state import RetrievedFact
from api.retrieval.hybrid import hybrid_search
from evals.run_concession_eval import _ScriptedConcessionLLM
from evals.run_retrieval_eval import _HashEmbedder, build_corpus
from evals.run_retrieval_eval import _load_dataset as _load_retrieval

DATASET_DIR = Path(__file__).parent / "dataset"
OUT_PATH = DATASET_DIR / "ragas.jsonl"

IRRELEVANT_CONTEXT = (
    "The Mumbai Metro Line 3 tunnel-boring project was completed ahead of "
    "schedule in the western suburbs."
)


def _load_concessions() -> list[dict[str, Any]]:
    with (DATASET_DIR / "concessions.jsonl").open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _build_document_entries() -> list[dict[str, Any]]:
    session = build_corpus(_HashEmbedder())
    try:
        chunks = list(session.scalars(select(DocumentChunk)).all())
        retrieval_dataset = _load_retrieval()[:15]

        entries: list[dict[str, Any]] = []
        for i, item in enumerate(retrieval_dataset):
            result = hybrid_search(session, _HashEmbedder(), item["query"], top_n=3)  # type: ignore[arg-type]
            retrieved = [c for c in chunks if c.id in result.chunk_ids]
            top_text = retrieved[0].text.replace("\n", " ").strip() if retrieved else ""
            ground_truth = top_text
            answer = f"Based on the document: {top_text[:200]}"
            contexts = [c.text.replace("\n", " ").strip() for c in retrieved]

            mode = i % 5  # 0,1,2 clean; 3 faithfulness-corrupted; 4 recall-corrupted
            entry_id = f"ragas_doc_{i + 1:02d}"
            if mode == 3 and contexts:
                answer = answer + " Volvo also offers free lifetime roadside towing worldwide."
                entries.append(
                    _entry(
                        entry_id,
                        "document",
                        item["query"],
                        answer,
                        contexts,
                        ground_truth,
                        {
                            "faithfulness": 0.5,
                            "answer_relevancy": 0.8,
                            "context_precision": 1.0,
                            "context_recall": 1.0,
                        },
                        "Second sentence ('free lifetime roadside towing worldwide') is "
                        "fabricated — not present in any retrieved chunk.",
                    )
                )
            elif mode == 4 and len(contexts) > 1:
                dropped_context = contexts[:1]
                entries.append(
                    _entry(
                        entry_id,
                        "document",
                        item["query"],
                        answer,
                        dropped_context,
                        ground_truth,
                        {
                            "faithfulness": 1.0,
                            "answer_relevancy": 0.8,
                            "context_precision": 1.0,
                            "context_recall": 0.5,
                        },
                        "One of the two retrieved chunks was deliberately dropped before "
                        "generation, so only part of the needed context made it through.",
                    )
                )
            else:
                entries.append(
                    _entry(
                        entry_id,
                        "document",
                        item["query"],
                        answer,
                        contexts,
                        ground_truth,
                        {
                            "faithfulness": 1.0,
                            "answer_relevancy": 0.8,
                            "context_precision": 1.0,
                            "context_recall": 1.0,
                        },
                        "Clean case: answer is a direct excerpt of the top retrieved chunk.",
                    )
                )
        return entries
    finally:
        session.close()


def _build_objection_entries() -> list[dict[str, Any]]:
    concessions = [e for e in _load_concessions() if e["customer_is_correct"]][:15]
    llm = _ScriptedConcessionLLM()

    entries: list[dict[str, Any]] = []
    for i, entry in enumerate(concessions):
        facts = [
            RetrievedFact(claim=f["claim"], source_id=j)
            for j, f in enumerate(entry["grounding_facts"])
        ]
        response = generate_response(llm, entry["objection"], facts, [])  # type: ignore[arg-type]
        contexts = [f.claim for f in facts] or ["No sourced fact was retrieved for this objection."]
        ground_truth = " ".join(contexts)
        answer = response.what_is_true

        mode = i % 5  # 0,1,2 clean; 3 answer_relevancy-corrupted; 4 context_precision-corrupted
        entry_id = f"ragas_obj_{i + 1:02d}"
        if mode == 3:
            off_topic_answer = "Volvo's infotainment system supports wireless Android Auto."
            entries.append(
                _entry(
                    entry_id,
                    "objection",
                    entry["objection"],
                    off_topic_answer,
                    contexts,
                    ground_truth,
                    {
                        "faithfulness": 0.0,
                        "answer_relevancy": 0.0,
                        "context_precision": 1.0,
                        "context_recall": 1.0,
                    },
                    "Answer swapped for an unrelated infotainment claim — doesn't "
                    "address the objection and isn't grounded in the retrieved facts.",
                )
            )
        elif mode == 4:
            noisy_contexts = [*contexts, IRRELEVANT_CONTEXT]
            entries.append(
                _entry(
                    entry_id,
                    "objection",
                    entry["objection"],
                    answer,
                    noisy_contexts,
                    ground_truth,
                    {
                        "faithfulness": 1.0,
                        "answer_relevancy": 0.7,
                        "context_precision": 1.0 - 1.0 / len(noisy_contexts),
                        "context_recall": 1.0,
                    },
                    "An unrelated context (a metro construction snippet) was mixed "
                    "into the retrieved set — retrieval precision, not the answer, is bad.",
                )
            )
        else:
            entries.append(
                _entry(
                    entry_id,
                    "objection",
                    entry["objection"],
                    answer,
                    contexts,
                    ground_truth,
                    {
                        "faithfulness": 1.0,
                        "answer_relevancy": 0.7,
                        "context_precision": 1.0,
                        "context_recall": 1.0,
                    },
                    "Clean case: response echoes exactly the retrieved facts.",
                )
            )
    return entries


def _entry(
    entry_id: str,
    track: str,
    question: str,
    answer: str,
    contexts: list[str],
    ground_truth: str,
    hand_labels: dict[str, float],
    notes: str,
) -> dict[str, Any]:
    return {
        "id": entry_id,
        "track": track,
        "question": question,
        "answer": answer,
        "contexts": contexts,
        "ground_truth": ground_truth,
        "hand_labels": hand_labels,
        "notes": notes,
    }


def main() -> None:
    entries = _build_document_entries() + _build_objection_entries()
    with OUT_PATH.open("w", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")
    print(f"Wrote {len(entries)} entries to {OUT_PATH}")


if __name__ == "__main__":
    main()
