"""evals/ragas_metrics.py — RAGAS-style metrics (T4.6).

docs/RETRIEVAL.md, Layer 1: faithfulness, answer relevancy, context
precision, context recall — "the field-standard metrics," run on the
objection and document tracks, with a 30-example hand-labelled
judge-agreement check since "RAGAS scores are LLM-judged and noisy."

**Deliberate substitution, documented rather than hidden:** the real `ragas`
PyPI package requires a LangChain-wrapped LLM judge to actually score
anything — a new heavy dependency chain (`langchain-core`, a chat-model
adapter, `datasets`) on top of a vendor call this sandbox doesn't have a key
for (`OPENAI_API_KEY` — see T4.2c/T4.4). This project has already made the
same call in the other direction more than once (no `sentence-transformers`
+ `torch` for reranking in T4.2c, no new vendor SDK for the same reason): a
big dependency purely to wrap a call this environment can't make yet isn't
worth it. So this module implements the same four metric *definitions*
RAGAS uses, as deterministic lexical-overlap scorers — the same "exercise
the real decision logic, be honest that it's a proxy for genuine semantic
judgement" pattern as `api/objection/verify.py`'s grounding check and
T4.2b/T4.2c's hash-embedder/lexical-overlap stand-ins. The functions below
take plain text in and a float out specifically so a real LLM-judge
implementation (RAGAS proper, or a hand-rolled prompt against `LLMClient`)
can be dropped in later without changing `run_ragas_eval.py`'s shape.

Each metric is a fraction of "hits" over a denominator, matching RAGAS's own
0.0-1.0 scale:

- `faithfulness(answer, contexts)` — fraction of the answer's sentences whose
  significant tokens are substantially covered by the retrieved contexts.
- `answer_relevancy(answer, question)` — token overlap between the answer
  and the question it's meant to address.
- `context_precision(contexts, ground_truth)` — fraction of the retrieved
  contexts that are actually about the ground truth.
- `context_recall(contexts, ground_truth)` — fraction of the ground truth's
  significant content that shows up somewhere in the retrieved contexts.
"""

from __future__ import annotations

import re

OVERLAP_THRESHOLD = 0.5

_STOPWORDS = frozenset(
    "a an the is are was were be been being to of in on at for and or but with "
    "this that these those it its as by from not no does do has have can will "
    "would should could".split()
)

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def _tokenize(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {w for w in words if w not in _STOPWORDS and len(w) > 2}


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_SPLIT_RE.split(text.strip()) if s.strip()]


def _overlap_ratio(a_tokens: set[str], b_tokens: set[str]) -> float:
    if not a_tokens:
        return 1.0
    return len(a_tokens & b_tokens) / len(a_tokens)


def faithfulness(answer: str, contexts: list[str]) -> float:
    sentences = _sentences(answer)
    if not sentences:
        return 1.0
    context_tokens = _tokenize(" ".join(contexts))
    grounded = sum(
        1 for s in sentences if _overlap_ratio(_tokenize(s), context_tokens) >= OVERLAP_THRESHOLD
    )
    return grounded / len(sentences)


def answer_relevancy(answer: str, question: str) -> float:
    return _overlap_ratio(_tokenize(question), _tokenize(answer))


def context_precision(contexts: list[str], ground_truth: str) -> float:
    if not contexts:
        return 0.0
    gt_tokens = _tokenize(ground_truth)
    relevant = sum(
        1 for c in contexts if _overlap_ratio(_tokenize(c), gt_tokens) >= OVERLAP_THRESHOLD
    )
    return relevant / len(contexts)


def context_recall(contexts: list[str], ground_truth: str) -> float:
    return _overlap_ratio(_tokenize(ground_truth), _tokenize(" ".join(contexts)))
