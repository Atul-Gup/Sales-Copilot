from api.objection.state import GeneratedResponse, RetrievedChunk, RetrievedFact
from api.objection.verify import (
    check_concession,
    check_grounding,
    extract_claims_deterministic,
    verify_grounding,
)


def test_extract_claims_deterministic_splits_on_sentences() -> None:
    text = "Volvo has 5 service centres. That is fewer than BMW's count."
    assert extract_claims_deterministic(text) == [
        "Volvo has 5 service centres.",
        "That is fewer than BMW's count.",
    ]


def test_extract_claims_deterministic_returns_empty_list_for_empty_text() -> None:
    assert extract_claims_deterministic("   ") == []


def test_extract_claims_deterministic_returns_single_claim_for_one_sentence() -> None:
    assert extract_claims_deterministic("Volvo has 5 service centres.") == [
        "Volvo has 5 service centres."
    ]


def test_check_grounding_passes_claim_backed_by_a_fact() -> None:
    facts = [RetrievedFact(claim="Volvo has 5 ingested service centres", source_id=1)]
    violations = check_grounding(["Volvo has 5 ingested service centres"], facts, [])
    assert violations == []


def test_check_grounding_flags_a_claim_with_no_support() -> None:
    violations = check_grounding(["The XC90 has a titanium chassis"], [], [])
    assert len(violations) == 1
    assert "titanium chassis" in violations[0]


def test_check_grounding_passes_a_paraphrased_claim_citing_a_short_number() -> None:
    """Regression: `_tokenize` used to drop numeric tokens of length <= 2
    ("11", "12", "60"), so a claim correctly restating a real retrieved
    figure like "11.2 in" was failing grounding for lack of overlap on the
    one token that actually mattered — a real bug found streaming a live
    XC60-vs-X3 comparison in production (T7.4)."""
    facts = [RetrievedFact(claim="variant 1 centre_display_in: 11.2 in", source_id=1)]
    violations = check_grounding(["The vehicle comes with an 11.2-inch centre display."], facts, [])
    assert violations == []


def test_check_grounding_passes_a_verbose_claim_whose_every_number_is_grounded() -> None:
    """Regression: a real GPT-generated compound sentence citing several
    genuinely retrieved figures in verbose prose was failing the word-overlap
    ratio purely on filler words, even though every number in it was real —
    found streaming a live XC60-vs-X3 comparison in production (T7.4)."""
    facts = [
        RetrievedFact(claim="variant 1 overall_length_mm: 4708", source_id=1),
        RetrievedFact(claim="variant 1 overall_width_mm: 1902", source_id=1),
        RetrievedFact(claim="variant 1 driver_display_in: 12.3", source_id=1),
    ]
    claim = (
        "Its dimensions—such as overall length of 4708 mm and width of "
        "1902 mm—along with its 12.3-inch driver display, may contribute "
        "to a spacious and comfortable interior experience."
    )
    assert check_grounding([claim], facts, []) == []


def test_check_grounding_still_flags_a_claim_with_one_invented_number() -> None:
    """The verbose-claim forgiveness above must not create a loophole: a
    claim citing even one number absent from the retrieved context still
    fails, regardless of how many other real numbers it also cites."""
    facts = [RetrievedFact(claim="variant 1 overall_length_mm: 4708", source_id=1)]
    claim = "The XC60 is 4708 mm long and tows up to 9999 kg."
    violations = check_grounding([claim], facts, [])
    assert len(violations) == 1


def test_check_grounding_passes_claim_backed_by_a_chunk() -> None:
    chunks = [
        RetrievedChunk(
            text="The warranty covers powertrain defects for 5 years",
            document_title="Warranty",
            page=1,
            source_id=2,
        )
    ]
    violations = check_grounding(["the warranty covers powertrain defects"], [], chunks)
    assert violations == []


def test_check_concession_skips_categories_outside_known_weaknesses() -> None:
    response = GeneratedResponse(
        what_is_true="", how_to_frame_it="", what_not_to_claim="", raw_text=""
    )
    assert check_concession("spec_comparison", [], response) == []


def test_check_concession_flags_missing_acknowledgement() -> None:
    response = GeneratedResponse(
        what_is_true="Volvo has great cars.",
        how_to_frame_it="Talk about safety.",
        what_not_to_claim="",
        raw_text="",
    )
    violations = check_concession("service_network", [], response)
    assert any("acknowledge" in v for v in violations)


def test_check_concession_flags_missing_figure_when_facts_present() -> None:
    facts = [RetrievedFact(claim="Volvo has 5 ingested service centres", source_id=1)]
    response = GeneratedResponse(
        what_is_true="That's a fair point, we do have a smaller footprint.",
        how_to_frame_it="Mention roadside assistance.",
        what_not_to_claim="",
        raw_text="",
    )
    violations = check_concession("service_network", facts, response)
    assert any("cite the retrieved figure" in v for v in violations)


def test_check_concession_passes_well_formed_response() -> None:
    facts = [RetrievedFact(claim="Volvo has 5 ingested service centres", source_id=1)]
    what_is_true = "That's a fair point — Volvo has 5 ingested service centres, fewer than rivals."
    response = GeneratedResponse(
        what_is_true=what_is_true,
        how_to_frame_it="Acknowledge the gap and mention roadside assistance.",
        what_not_to_claim="Don't promise a new centre opening.",
        raw_text="",
    )
    assert check_concession("service_network", facts, response) == []


def test_verify_grounding_combines_grounding_and_concession_checks() -> None:
    response = GeneratedResponse(
        what_is_true="Volvo has invented feature X.",
        how_to_frame_it="x",
        what_not_to_claim="",
        raw_text="",
    )
    violations = verify_grounding("service_network", [], [], response)
    assert any("unsupported_claim" in v for v in violations)
    assert any("acknowledge" in v for v in violations)


def test_verify_grounding_passes_a_grounded_claim_with_no_concession_needed() -> None:
    facts = [RetrievedFact(claim="Volvo has 5 ingested service centres", source_id=1)]
    response = GeneratedResponse(
        what_is_true="Volvo has 5 ingested service centres.",
        how_to_frame_it="x",
        what_not_to_claim="",
        raw_text="",
    )
    assert verify_grounding("spec_comparison", facts, [], response) == []
