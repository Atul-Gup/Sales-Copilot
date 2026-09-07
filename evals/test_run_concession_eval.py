from api.llm.client import Message
from evals.run_concession_eval import _ScriptedConcessionLLM, run_concession_eval


def test_scripted_concession_llm_echoes_facts_into_what_is_true() -> None:
    prompt = (
        "Customer objection: Volvo barely has service centres\n\n"
        "Facts:\n"
        "- Volvo has 5 ingested service centres (source_id=0)\n\n"
        "Document excerpts:\n"
        "- none retrieved"
    )
    llm = _ScriptedConcessionLLM()
    result = llm.complete([Message(role="user", content=prompt)])
    assert "Volvo has 5 ingested service centres" in result.text
    assert "WHAT'S TRUE:" in result.text
    assert "HOW TO FRAME IT:" in result.text


def test_scripted_concession_llm_handles_no_facts() -> None:
    prompt = (
        "Customer objection: Volvos depreciate faster\n\nFacts:\n"
        "- none retrieved\n\nDocument excerpts:\n- none retrieved"
    )
    llm = _ScriptedConcessionLLM()
    result = llm.complete([Message(role="user", content=prompt)])
    assert "fair point" in result.text


def test_run_concession_eval_only_scores_customer_is_right_cases() -> None:
    results = run_concession_eval()
    ids = {e["id"] for e in results["per_entry"]}
    assert "conc_009" not in ids  # negative control, customer_is_correct: false
    assert "conc_020" not in ids  # negative control, customer_is_correct: false
    assert "conc_001" in ids
    assert results["n_customer_is_right_cases"] == len(ids)


def test_run_concession_eval_reports_a_rate_between_zero_and_one() -> None:
    results = run_concession_eval()
    assert 0.0 <= results["honest_concession_rate"] <= 1.0
    assert results["n_customer_is_right_cases"] > 0
