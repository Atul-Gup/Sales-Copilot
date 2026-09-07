"""Structural validation for `retrieval.jsonl` (T4.2b, docs/RETRIEVAL.md
Layer 3: retrieval evaluated alone, before any end-to-end number).

This just guards the dataset's shape; `evals/run_retrieval_eval.py` is what
actually scores dense/sparse/hybrid retrieval against it.
"""

import json
from pathlib import Path
from typing import Any

DATASET_PATH = Path(__file__).parent / "retrieval.jsonl"

KNOWN_DOCUMENT_TITLES = {
    "Volvo Warranty (India)",
    "Euro NCAP | XC60",
    "Euro NCAP | EX30",
    "Euro NCAP | GLC",
    "Euro NCAP | Q5",
}

REQUIRED_KEYS = {"id", "query", "relevant", "favors"}
ALLOWED_FAVORS = {"dense", "sparse", "either"}


def _load_entries() -> list[dict[str, Any]]:
    with DATASET_PATH.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def test_dataset_has_twenty_four_entries() -> None:
    assert len(_load_entries()) == 24


def test_every_entry_has_required_keys() -> None:
    for entry in _load_entries():
        missing = REQUIRED_KEYS - entry.keys()
        assert not missing, f"{entry.get('id')} missing keys: {missing}"


def test_ids_are_unique() -> None:
    ids = [entry["id"] for entry in _load_entries()]
    assert len(ids) == len(set(ids))


def test_every_entry_has_at_least_one_relevant_chunk() -> None:
    for entry in _load_entries():
        assert entry["relevant"], entry["id"]
        for ref in entry["relevant"]:
            assert ref["document_title"] in KNOWN_DOCUMENT_TITLES, entry["id"]
            assert isinstance(ref["page"], int) and ref["page"] >= 1, entry["id"]


def test_favors_is_from_the_allowed_set() -> None:
    for entry in _load_entries():
        assert entry["favors"] in ALLOWED_FAVORS, entry["id"]


def test_all_known_documents_are_covered() -> None:
    covered = {ref["document_title"] for entry in _load_entries() for ref in entry["relevant"]}
    assert covered == KNOWN_DOCUMENT_TITLES


def test_both_dense_and_sparse_favoured_queries_are_present() -> None:
    # A dataset that's all one flavour can't show a hybrid ablation is doing
    # anything — it needs cases where each retriever alone would plausibly miss.
    favors = {entry["favors"] for entry in _load_entries()}
    assert "dense" in favors
    assert "sparse" in favors
