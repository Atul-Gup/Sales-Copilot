from evals.metrics import (
    LatencySample,
    citation_validity_rate,
    hallucinated_fact_rate,
    honest_concession_rate,
    in_corpus_recall,
    latency_by_intent,
    numeric_fidelity_rate,
    out_of_corpus_refusal_rate,
    over_refusal_rate,
    refusal_accuracy,
)


def test_numeric_fidelity_rate_perfect_when_all_values_present() -> None:
    response = "The XC60 has a wheelbase of 2865 mm and a ground clearance of 211 mm."
    expected = [
        {"value": "2865", "unit": "mm", "label": "wheelbase"},
        {"value": "211", "unit": "mm", "label": "ground clearance"},
    ]
    assert numeric_fidelity_rate(response, expected) == 1.0


def test_numeric_fidelity_rate_catches_a_wrong_number() -> None:
    response = "The XC60 has a wheelbase of 2800 mm."
    expected = [{"value": "2865", "unit": "mm", "label": "wheelbase"}]
    assert numeric_fidelity_rate(response, expected) == 0.0


def test_numeric_fidelity_rate_is_partial_when_some_values_missing() -> None:
    response = "The XC60 has a wheelbase of 2865 mm."
    expected = [
        {"value": "2865", "unit": "mm", "label": "wheelbase"},
        {"value": "211", "unit": "mm", "label": "ground clearance"},
    ]
    assert numeric_fidelity_rate(response, expected) == 0.5


def test_numeric_fidelity_rate_is_vacuously_perfect_with_no_expected_values() -> None:
    assert numeric_fidelity_rate("no numbers relevant here", []) == 1.0


def test_numeric_fidelity_rate_handles_comma_separated_numbers() -> None:
    response = "The audio system puts out 1,410 W through 15 speakers."
    expected = [{"value": "1410", "unit": "W", "label": "audio power"}]
    assert numeric_fidelity_rate(response, expected) == 1.0


def test_citation_validity_rate_valid_numeric_citation() -> None:
    claim = "The XC60's wheelbase is 2865 mm."
    chunk = "Wheelbase: 2865 mm. Overall length: 4708 mm."
    assert citation_validity_rate([(claim, chunk)]) == 1.0


def test_citation_validity_rate_invalid_numeric_citation() -> None:
    claim = "The XC60's wheelbase is 2865 mm."
    chunk = "Overall length: 4708 mm. Boot capacity: not specified."
    assert citation_validity_rate([(claim, chunk)]) == 0.0


def test_citation_validity_rate_non_numeric_claim_falls_back_to_word_overlap() -> None:
    claim = "The XC60 has a panoramic roof."
    chunk = "Panoramic roof: shown/described in the interior section."
    assert citation_validity_rate([(claim, chunk)]) == 1.0


def test_citation_validity_rate_empty_list_is_vacuously_perfect() -> None:
    assert citation_validity_rate([]) == 1.0


def test_hallucinated_fact_rate_flags_an_unsupported_number() -> None:
    claims = ["The XC60's wheelbase is 3000 mm."]
    retrieved = ["Wheelbase: 2865 mm."]
    assert hallucinated_fact_rate(claims, retrieved) == 1.0


def test_hallucinated_fact_rate_clears_a_supported_number() -> None:
    claims = ["The XC60's wheelbase is 2865 mm."]
    retrieved = ["Wheelbase: 2865 mm."]
    assert hallucinated_fact_rate(claims, retrieved) == 0.0


def test_hallucinated_fact_rate_is_zero_with_no_claims() -> None:
    assert hallucinated_fact_rate([], ["some retrieved text"]) == 0.0


def test_rate_wrappers_compute_a_simple_fraction() -> None:
    assert in_corpus_recall([True, True, False, True]) == 0.75
    assert out_of_corpus_refusal_rate([True, True]) == 1.0
    assert honest_concession_rate([False, False]) == 0.0
    assert refusal_accuracy([True, False, True, True]) == 0.75
    assert abs(over_refusal_rate([False, False, True]) - 1 / 3) < 1e-9


def test_rate_wrappers_are_zero_on_empty_input() -> None:
    assert in_corpus_recall([]) == 0.0
    assert refusal_accuracy([]) == 0.0


def test_latency_by_intent_computes_percentiles_per_intent() -> None:
    samples = [
        LatencySample(intent="SPEC", latency_ms=100.0),
        LatencySample(intent="SPEC", latency_ms=200.0),
        LatencySample(intent="COMPARISON", latency_ms=500.0),
    ]
    result = latency_by_intent(samples)
    assert set(result.keys()) == {"SPEC", "COMPARISON"}
    assert result["SPEC"]["mean"] == 150.0
    assert result["COMPARISON"]["p50"] == 500.0
    assert result["COMPARISON"]["p95"] == 500.0


def test_latency_by_intent_handles_a_single_sample_per_intent() -> None:
    samples = [LatencySample(intent="OBJECTION", latency_ms=300.0)]
    result = latency_by_intent(samples)
    assert result["OBJECTION"]["p50"] == 300.0
    assert result["OBJECTION"]["p95"] == 300.0
