"""Structural validation for `ragas.jsonl` (T4.6). `run_ragas_eval.py` is
what actually scores against it — this just guards the dataset's shape.
"""

import json
from pathlib import Path
from typing import Any

DATASET_PATH = Path(__file__).parent / "ragas.jsonl"

REQUIRED_KEYS = {"id", "track", "question", "answer", "contexts", "ground_truth", "hand_labels"}
ALLOWED_TRACKS = {"document", "objection"}
REQUIRED_METRICS = {"faithfulness", "answer_relevancy", "context_precision", "context_recall"}


def _load_entries() -> list[dict[str, Any]]:
    with DATASET_PATH.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def test_dataset_has_30_entries() -> None:
    assert len(_load_entries()) == 30


def test_every_entry_has_the_required_keys() -> None:
    for entry in _load_entries():
        assert REQUIRED_KEYS.issubset(entry.keys()), entry["id"]


def test_ids_are_unique() -> None:
    ids = [e["id"] for e in _load_entries()]
    assert len(ids) == len(set(ids))


def test_track_is_document_or_objection() -> None:
    for entry in _load_entries():
        assert entry["track"] in ALLOWED_TRACKS, entry["id"]


def test_both_tracks_have_15_entries() -> None:
    entries = _load_entries()
    for track in ALLOWED_TRACKS:
        assert sum(1 for e in entries if e["track"] == track) == 15


def test_hand_labels_cover_all_four_metrics_in_range() -> None:
    for entry in _load_entries():
        labels = entry["hand_labels"]
        assert set(labels.keys()) == REQUIRED_METRICS, entry["id"]
        for value in labels.values():
            assert 0.0 <= value <= 1.0, entry["id"]


def test_hand_labels_span_a_real_range_not_all_perfect() -> None:
    """A dataset that's all 1.0s can't validate whether the judge catches a
    real problem — see build_ragas_dataset.py's deliberate corruption.
    """
    all_values = [v for e in _load_entries() for v in e["hand_labels"].values()]
    assert min(all_values) < 0.8
    assert max(all_values) == 1.0
