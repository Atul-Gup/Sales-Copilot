"""api/guardrails/test_output.py — one test per output rule (T5.3).

`must_concede` is intentionally absent — it's already tested in
`api/objection/test_verify.py` against `api/objection/verify.py`'s
`check_concession`, which needs the objection's category and retrieved
facts to judge, unlike every check in this module. Bad/good example text
for each rule mirrors the scenario `evals/dataset/redteam.jsonl`'s matching
category describes (a generated response that complies vs. one that
doesn't), not the red-team prompt itself — these rules fire on *output*,
not on the request that provoked it.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from api.guardrails.output import (
    check_cross_protocol_safety,
    check_delivery_promise,
    check_discount_promise,
    check_disparagement,
    check_no_clinical_certainty,
    check_on_road_price,
    check_service_overstatement,
    check_stale_data,
    check_uncited_claim,
    run_output_guardrails,
)


def test_uncited_claim() -> None:
    bad = "The XC60 has more boot space than the BMW X3."
    good = "The XC60 has more boot space than the BMW X3, per the official spec sheet."
    bad_result = check_uncited_claim(bad)
    assert bad_result is not None
    assert bad_result.rule_id == "uncited_claim"
    assert bad_result.action == "REWRITE"
    assert check_uncited_claim(good) is None


def test_uncited_claim_accepts_the_real_bracket_citation_convention() -> None:
    """Real user report: a properly `[n]`-cited comparison was refused after
    two generation attempts because this check's attribution regex only
    recognized prose phrasing ("per the spec sheet"), never the `[n]`
    marker every generated response actually uses — see this module's
    `_ATTRIBUTION_RE` docstring note."""
    cited = "The XC60 has more boot space than the BMW X3 [4]."
    assert check_uncited_claim(cited) is None


def test_cross_protocol_safety() -> None:
    bad = "The XC60's Euro NCAP score is equivalent to a 5-star Bharat NCAP rating."
    good = "The XC60 scored well under Euro NCAP's 2017 protocol."
    bad_result = check_cross_protocol_safety(bad)
    assert bad_result is not None
    assert bad_result.rule_id == "cross_protocol_safety"
    assert bad_result.action == "REFUSE"
    assert check_cross_protocol_safety(good) is None


def test_disparagement() -> None:
    bad = "The GLC just feels cheap and is badge-engineered junk next to the XC60."
    good = "The GLC scored 26.19/32 overall versus the XC60's figure from its own test."
    bad_result = check_disparagement(bad)
    assert bad_result is not None
    assert bad_result.rule_id == "disparagement"
    assert bad_result.action == "REWRITE"
    assert check_disparagement(good) is None


def test_service_overstatement() -> None:
    bad = "Confirm we have service coverage nationwide, including Indore."
    good = "Volvo has an ingested service centre in Mumbai; Indore isn't in the data."
    bad_result = check_service_overstatement(bad)
    assert bad_result is not None
    assert bad_result.rule_id == "service_overstatement"
    assert bad_result.action == "REFUSE"
    assert check_service_overstatement(good) is None


def test_service_overstatement_flags_uncovered_city_when_known_cities_given() -> None:
    known_cities = frozenset({"mumbai", "delhi"})
    bad = "Volvo has a service centre in Pune, so coverage there is confirmed."
    result = check_service_overstatement(bad, known_service_cities=known_cities)
    assert result is not None
    assert result.rule_id == "service_overstatement"


def test_on_road_price() -> None:
    bad = "The on-road price of the XC60 in Bhopal is Rs 65 lakh."
    good = (
        "The on-road price varies by city registration; ex-showroom is "
        "not sourced for this variant."
    )
    bad_result = check_on_road_price(bad)
    assert bad_result is not None
    assert bad_result.rule_id == "on_road_price"
    assert bad_result.action == "REFUSE"
    assert check_on_road_price(good) is None


def test_delivery_promise() -> None:
    bad = "The EX30 will definitely arrive within 6 weeks."
    good = "Delivery timelines depend on the dealer — please check with them directly."
    bad_result = check_delivery_promise(bad)
    assert bad_result is not None
    assert bad_result.rule_id == "delivery_promise"
    assert bad_result.action == "REFUSE"
    assert check_delivery_promise(good) is None


def test_discount_promise() -> None:
    bad = "We can knock off 5 lakh from the XC60 if they sign today."
    good = "Discount authority sits with the dealership's finance desk, not this tool."
    bad_result = check_discount_promise(bad)
    assert bad_result is not None
    assert bad_result.rule_id == "discount_promise"
    assert bad_result.action == "REFUSE"
    assert check_discount_promise(good) is None


def test_no_clinical_certainty() -> None:
    bad = "The XC60's resale value will definitely be worth 60% after five years."
    good = "This TCO figure is an estimate built from the assumptions shown, not guaranteed."
    bad_result = check_no_clinical_certainty(bad)
    assert bad_result is not None
    assert bad_result.rule_id == "no_clinical_certainty"
    assert bad_result.action == "ANNOTATE"
    assert check_no_clinical_certainty(good) is None


def test_stale_data() -> None:
    stale_after = datetime(2026, 1, 1)
    fresh_reference = datetime(2025, 12, 1)
    late_reference = datetime(2026, 2, 1)
    bad_result = check_stale_data(stale_after, late_reference)
    assert bad_result is not None
    assert bad_result.rule_id == "stale_data"
    assert bad_result.action == "REFUSE"
    assert check_stale_data(stale_after, fresh_reference) is None


def test_run_output_guardrails_collects_every_violation() -> None:
    text = (
        "The EX30 will definitely arrive within 6 weeks, and we can knock off "
        "5 lakh if they sign today."
    )
    violations = run_output_guardrails(text)
    rule_ids = {v.rule_id for v in violations}
    assert "delivery_promise" in rule_ids
    assert "discount_promise" in rule_ids


def test_run_output_guardrails_includes_stale_check_only_when_dates_given() -> None:
    text = "The XC60 has good boot space."
    assert run_output_guardrails(text) == []
    stale_after = datetime(2026, 1, 1)
    late_reference = stale_after + timedelta(days=1)
    violations = run_output_guardrails(text, stale_after=stale_after, reference_time=late_reference)
    assert any(v.rule_id == "stale_data" for v in violations)


def test_run_output_guardrails_clean_response_has_no_violations() -> None:
    text = (
        "The XC60 has more boot space than the BMW X3, per the official spec "
        "sheet. Delivery timelines depend on the dealer."
    )
    assert run_output_guardrails(text) == []
