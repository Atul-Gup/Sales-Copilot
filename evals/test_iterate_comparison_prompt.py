from evals.iterate_comparison_prompt import COMPARISON_PAIRS, VERSIONS, _expected_values, _score


def test_versions_are_strictly_additive() -> None:
    v1, v2, v3, v4 = VERSIONS["v1"], VERSIONS["v2"], VERSIONS["v3"], VERSIONS["v4"]
    assert v1 in v2
    assert v2 in v3
    assert v3 in v4


def test_comparison_pairs_resolve_against_qa_dataset() -> None:
    import json
    from pathlib import Path

    qa = [
        json.loads(line)
        for line in (Path(__file__).parent / "dataset" / "qa.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    for label, model_a, model_b in COMPARISON_PAIRS:
        assert _expected_values(qa, label, model_a)
        assert _expected_values(qa, label, model_b)


def test_score_detects_present_and_missing_numbers() -> None:
    expected = [{"value": "2,865", "unit": "mm"}, {"value": "750", "unit": "W"}]
    result = _score("The XC60 is 2865 mm.", expected)
    assert result == {"has_2,865": True, "has_750": False}
