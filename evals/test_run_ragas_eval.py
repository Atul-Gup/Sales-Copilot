from evals.run_ragas_eval import run_ragas_eval, score_entry


def test_score_entry_returns_all_four_metrics() -> None:
    entry = {
        "question": "How many service centres?",
        "answer": "Volvo has 5 service centres.",
        "contexts": ["Volvo has 5 service centres in the dataset."],
        "ground_truth": "Volvo has 5 service centres",
    }
    scores = score_entry(entry)
    assert set(scores) == {
        "faithfulness",
        "answer_relevancy",
        "context_precision",
        "context_recall",
    }
    for value in scores.values():
        assert 0.0 <= value <= 1.0


def test_run_ragas_eval_covers_the_full_dataset() -> None:
    results = run_ragas_eval()
    assert results["n_entries"] == 30
    assert results["n_document_track"] == 15
    assert results["n_objection_track"] == 15


def test_run_ragas_eval_reports_a_judge_agreement_rate() -> None:
    results = run_ragas_eval()
    assert 0.0 <= results["judge_agreement_rate"] <= 1.0
    # 30 entries * 4 metrics = 120 comparisons; agreements + disagreements must add up.
    assert len(results["disagreements"]) <= 120


def test_run_ragas_eval_reports_per_track_metric_breakdown() -> None:
    results = run_ragas_eval()
    assert set(results["metrics_by_track"]) == {"document", "objection"}
    for metrics in results["metrics_by_track"].values():
        assert set(metrics) == {
            "faithfulness",
            "answer_relevancy",
            "context_precision",
            "context_recall",
        }
