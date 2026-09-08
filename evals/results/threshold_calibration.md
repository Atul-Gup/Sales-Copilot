# in_corpus? threshold calibration (T3.6)

Scored against 32 qa.jsonl questions and 29 out_of_corpus.jsonl questions (excluding ['ooc_006'], the documented mixed case).

Signal: `hybrid_search_scored`'s fused RRF score (no reranker score exists post-T2.2).

| threshold | in_corpus_recall | out_of_corpus_refusal_rate |
|---|---|---|
| 0.000000 | 100.00% | 0.00% |
| 0.030835 | 100.00% | 3.45% |
| 0.031746 | 100.00% | 3.45% |
| 0.031754 | 100.00% | 6.90% |
| 0.031778 | 100.00% | 10.34% |
| 0.032018 | 90.62% | 10.34% |
| 0.032258 | 87.50% | 10.34% |
| 0.032266 | 84.38% | 13.79% |
| 0.032522 | 65.62% | 17.24% |
| 0.032787 | 0.00% | 100.00% |

**Chosen threshold: 0.031778** — does NOT clear both docs/PRD.md §6 targets simultaneously at this corpus size — best balanced point available; retrieval/corpus work is needed before generation, not a threshold tweak.
At this threshold: in_corpus_recall = 100.00%, out_of_corpus_refusal_rate = 10.34%.
