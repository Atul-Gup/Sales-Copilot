import time

import pytest

from api.services.router import QueryType, classify

LABELLED_QUERIES: list[tuple[str, QueryType]] = [
    # SPEC — single entity or none, plain factual asks
    ("What is the boot space of the XC60?", QueryType.SPEC),
    ("How many airbags does the GLC have?", QueryType.SPEC),
    ("What's the ground clearance of the XC40?", QueryType.SPEC),
    ("Does the X3 have a panoramic sunroof?", QueryType.SPEC),
    ("What is the boot capacity of the Q5?", QueryType.SPEC),
    ("List the safety features of the EX30.", QueryType.SPEC),
    ("What's the engine displacement of the S90?", QueryType.SPEC),
    ("How much horsepower does the XC90 have?", QueryType.SPEC),
    ("What is the wheelbase of the Q3?", QueryType.SPEC),
    ("Does the iX1 come with adaptive cruise control?", QueryType.SPEC),
    ("What color options are available for the XC60?", QueryType.SPEC),
    ("What is the price of the base XC40 variant?", QueryType.SPEC),
    ("How many seats does the XC90 have?", QueryType.SPEC),
    ("What is the towing capacity of the XC60?", QueryType.SPEC),
    ("Which variants have a panoramic roof under 70 lakh?", QueryType.SPEC),
    ("What's the fuel tank capacity of the S60?", QueryType.SPEC),
    ("Does the GLE have Apple CarPlay?", QueryType.SPEC),
    # COMPARISON — explicit vs./compare wording, or two+ brand/model mentions
    ("Compare the XC60 and the X3.", QueryType.COMPARISON),
    ("XC60 vs X3 boot space", QueryType.COMPARISON),
    ("What's the difference between the GLC and the XC60?", QueryType.COMPARISON),
    ("Is the Q5 better than the XC60?", QueryType.COMPARISON),
    ("Volvo XC90 versus BMW X7", QueryType.COMPARISON),
    ("Which is better, the Audi Q5 or the Mercedes GLC?", QueryType.COMPARISON),
    ("How does the XC60 compare to the X3?", QueryType.COMPARISON),
    ("GLC vs GLE", QueryType.COMPARISON),
    ("Volvo vs BMW safety ratings", QueryType.COMPARISON),
    ("XC40 and Q3 comparison", QueryType.COMPARISON),
    ("Is the S90 better than the S60?", QueryType.COMPARISON),
    ("Q3 or X1, which one is bigger?", QueryType.COMPARISON),
    ("Mercedes GLC versus Audi Q5 ground clearance", QueryType.COMPARISON),
    ("XC90 or GLE, which has more boot space", QueryType.COMPARISON),
    ("BMW X3 and Audi Q5 spec comparison", QueryType.COMPARISON),
    ("Volvo XC60 vs Mercedes GLC vs Audi Q5", QueryType.COMPARISON),
    # OBJECTION — customer pushback, concern, or a claim to defend against
    ("My customer heard that Volvo has poor resale value.", QueryType.OBJECTION),
    ("The customer says BMW has better service network.", QueryType.OBJECTION),
    ("Why should I buy a Volvo instead of a BMW?", QueryType.OBJECTION),
    ("I'm worried about Volvo's service centers being far away.", QueryType.OBJECTION),
    ("My friend told me Mercedes has better resale value.", QueryType.OBJECTION),
    ("Isn't it true that Audi has faster acceleration?", QueryType.OBJECTION),
    ("I can get a BMW X3 for cheaper than the XC60.", QueryType.OBJECTION),
    ("The customer is concerned about the waiting period for delivery.", QueryType.OBJECTION),
    ("But doesn't Volvo have fewer service centers than BMW?", QueryType.OBJECTION),
    ("My neighbor said his Audi never had any problems.", QueryType.OBJECTION),
    ("Convince me why Volvo is worth the premium over Mercedes.", QueryType.OBJECTION),
    ("Why is the Volvo more expensive than the BMW for similar specs?", QueryType.OBJECTION),
    ("The customer heard from a colleague that Volvo has a long wait.", QueryType.OBJECTION),
    ("Why does Volvo have a smaller dealer network than Mercedes?", QueryType.OBJECTION),
    ("I read that Volvo's resale value drops fast, is that true?", QueryType.OBJECTION),
    ("But the Audi showroom is closer to my house, why go Volvo?", QueryType.OBJECTION),
    ("The customer is concerned service quality won't match BMW.", QueryType.OBJECTION),
]


def test_labelled_query_set_has_fifty_examples() -> None:
    assert len(LABELLED_QUERIES) == 50


@pytest.mark.parametrize("query,expected", LABELLED_QUERIES)
def test_classify_matches_label(query: str, expected: QueryType) -> None:
    assert classify(query) is expected


def test_classify_stays_under_the_latency_budget() -> None:
    start = time.perf_counter()
    classify("Compare the XC60 and the X3 on boot space.")
    elapsed_ms = (time.perf_counter() - start) * 1000
    assert elapsed_ms < 100
