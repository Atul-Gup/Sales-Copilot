from evals.ragas_metrics import answer_relevancy, context_precision, context_recall, faithfulness


def test_faithfulness_is_one_when_every_sentence_is_grounded() -> None:
    answer = "Volvo has 5 ingested service centres. Mercedes has 9."
    contexts = ["Volvo has 5 ingested service centres in the dataset.", "Mercedes has 9 centres."]
    assert faithfulness(answer, contexts) == 1.0


def test_faithfulness_drops_when_a_sentence_is_unsupported() -> None:
    answer = "Volvo has 5 ingested service centres. Volvo invented a self-repairing chassis."
    contexts = ["Volvo has 5 ingested service centres in the dataset."]
    score = faithfulness(answer, contexts)
    assert 0.0 < score < 1.0


def test_faithfulness_handles_empty_answer() -> None:
    assert faithfulness("", ["some context"]) == 1.0


def test_answer_relevancy_high_when_answer_addresses_question() -> None:
    question = "How many service centres does Volvo have?"
    answer = "Volvo has 5 ingested service centres."
    assert answer_relevancy(answer, question) > 0.5


def test_answer_relevancy_low_when_answer_is_off_topic() -> None:
    question = "How many service centres does Volvo have?"
    answer = "The weather in Mumbai is warm this time of year."
    assert answer_relevancy(answer, question) == 0.0


def test_context_precision_penalises_irrelevant_contexts() -> None:
    ground_truth = "Volvo has 5 ingested service centres"
    contexts = ["Volvo has 5 ingested service centres", "The capital of France is Paris"]
    score = context_precision(contexts, ground_truth)
    assert score == 0.5


def test_context_precision_is_zero_with_no_contexts() -> None:
    assert context_precision([], "some ground truth") == 0.0


def test_context_recall_penalises_missing_context() -> None:
    ground_truth = "Volvo has 5 ingested service centres and Mercedes has 9"
    contexts = ["Volvo has 5 ingested service centres"]
    score = context_recall(contexts, ground_truth)
    assert 0.0 < score < 1.0


def test_context_recall_is_one_when_all_ground_truth_is_covered() -> None:
    ground_truth = "Volvo has 5 ingested service centres"
    contexts = ["Volvo has 5 ingested service centres in the dataset"]
    assert context_recall(contexts, ground_truth) == 1.0
