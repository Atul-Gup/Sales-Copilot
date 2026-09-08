# RETRIEVAL — Showroom Copilot

How retrieval and generation work.

The one-line summary for an interview: **closed-book RAG over a curated document set, with a measured refusal behaviour when the answer isn't in the documents — one retrieval path, rendered as natural chat language, with guardrail content kept visible inside the prose.**

---

## Why closed-book is the harder, more interesting claim

An open system that cites sources when it has them is good practice. A **closed-book** system additionally has to recognise the boundary of its own knowledge and refuse past it — distinguishing "I found this in a document" from "I know this generally" and acting only on the former. That distinction, not the retrieval mechanics, is the core engineering problem in this version of the product.

---

## The corpus

Five documents — see `docs/CORPUS.md` for the authoritative list. One folder per brand:

```
data/sources/products/
├── volvo/{xc60, ex30}
├── bmw/x3
├── mercedes/glc
└── audi/q5
```

Every chunk carries `source_id NOT NULL`. No NCAP, no warranty, no service-plan documents — those questions are refused, not answered from the model's general knowledge. Service centre data is a separate structured source, checked by lookup, not part of this chunked corpus.

---

## Single retrieval path

```
query
  │
  ├─ classify_intent   → SPEC | COMPARISON | OBJECTION
  │                       (selects prompt style — does NOT skip retrieval,
  │                        and does not change WHETHER generation happens)
  │
  ├─ retrieve           hybrid: dense (pgvector) + BM25 + reciprocal rank fusion
  │                       → top 50 → cross-encoder rerank → top 5
  │
  ├─ in_corpus?         is the top reranked result above a calibrated
  │                     relevance threshold?
  │     │no                    │yes
  │     ▼                       ▼
  │  refuse_gracefully     generate
  │  (name what's           generate — LLM narration for all intent
  │   missing)               classes, over the retrieved chunks
  │                               │
  │                         verify_grounding
  │                         (checks every claim AND every number/
  │                          unit against the retrieved chunks —
  │                          numeric mismatch is a violation too)
  │                               │
  │                    violation? loop once (regen) → refuse
  │                               │no
  │                               ▼
  │                       render — citations and "don't claim"/
  │                       concession content stay visually distinct
  │                       inside the natural-language response
```

This whole path is built as a **LangGraph cycle**: `verify_grounding → generate → verify_grounding` is a genuine loop with a counter, which is the actual justification for using a graph framework here rather than plain function calls. State (retrieved context, attempt count, violations) is passed explicitly between nodes, and checkpointing gives replayable execution traces for free — feeding observability later.

---

## Hybrid retrieval and reranking

Dense embeddings alone under-perform on this corpus because it's full of exact-match tokens — trim names, engine codes, model years. BM25 catches those; dense catches paraphrase and synonymy. Fused with reciprocal rank fusion (no score normalisation needed, fuses on rank position). `api/services/retrieve.py::hybrid_search` implements this; see below for why a cross-encoder reranking pass on top of it was evaluated and dropped, at least for now.

**Embeddings:** OpenAI `text-embedding-3-small`, cached — compute once per chunk, don't re-embed unchanged content on every eval run. The `chunks.embedding` column is `vector(1536)` to match. Chosen because the corpus is small enough that embedding quality differences are unlikely to matter, and because it's already in the stack (no new vendor). Report a local-vs-hosted ablation once, to make the choice measured rather than assumed.

**Report the ablation** (dense-only vs sparse-only vs hybrid, with vs without reranking) on a labelled retrieval set. The table is worth more than the feature — it's evidence the choices were measured, not assumed. *(Blocked on `evals/dataset/qa.jsonl` existing — Phase 3, not built yet.)*

### Reranking decision (T2.2): dropped, not just deferred

A cross-encoder rerank over the fused top-50 was attempted with `sentence-transformers` (a local CPU model, e.g. `cross-encoder/ms-marco-MiniLM-L-6-v2`) and abandoned after two real install attempts — the default `torch` wheel and the dedicated CPU-only wheel from `download.pytorch.org/whl/cpu` both fail to load on this machine with `WinError 1114` (a DLL initialization failure in `c10.dll`), an environment-level issue, not a version mismatch. This is a real, measured piece of friction, not a hypothetical one.

Combined with the corpus's actual size — **49 chunks ingested from the 4 documents currently present, and not much more once the fifth (Mercedes GLC) lands** — a reranking pass over the fused top-50 is close to reranking the entire corpus for most queries. The precision gain a cross-encoder buys over BM25+dense fusion is a much harder case to make at this scale than at, say, thousands of chunks.

**Decision: skip the reranking stage.** `hybrid_search`'s fused ranking is passed directly to generation. Revisit if any of these changes materially:
- the corpus grows enough that top-50 stops being close to "everything" (many more documents/models added to `docs/CORPUS.md`), or
- a lighter-weight reranking option becomes available that doesn't require `torch` on this deployment target (a hosted rerank API, an ONNX-only cross-encoder runtime, or simply a different host where the DLL issue doesn't reproduce), or
- **(measured, not anticipated) the `in_corpus?` calibration below.** T3.6's actual calibration run found the fused RRF score cannot support a well-calibrated gate — see that section for the finding. This is the strongest of the three reasons to revisit, since it's evidence rather than a prediction.

---

## `in_corpus?` — the node that matters most

Retrieval returning *something* is not the same as returning something relevant. Vector and BM25 search will always return their nearest results, even when nothing in the corpus actually answers the question.

**Calibrate the threshold, don't default it:**
1. Build `qa.jsonl` — 30+ questions genuinely answerable from the five documents. *(Done, T3.1 — 32 questions across the 4 currently-sourced documents.)*
2. Build `out_of_corpus.jsonl` — 30 questions with no supporting document: safety ratings, warranty terms, on-road pricing, anything deliberately not ingested. *(Done, T3.2 — 30 questions across 7 categories.)*
3. Sweep the threshold across both sets; pick the point that best trades off the two error types; report the curve, not just the chosen point. *(Done, T3.6 — `evals/calibrate_threshold.py`, results in `evals/results/threshold_calibration.md`. Since T2.2 dropped the reranker, there is no reranker score to sweep; this sweeps `hybrid_search_scored`'s fused RRF score instead — see the finding below.)*

### T3.6 finding: the RRF score is a poor `in_corpus?` signal without reranking

The calibration run against the real corpus (49 chunks) surfaced a real, measured consequence of T2.2's "drop the reranker" decision, not just the anticipated latency/install-friction tradeoff: **the fused RRF score does not separate in-corpus from out-of-corpus questions smoothly.** The curve has a cliff, not a slope — between two adjacent observed scores, `out_of_corpus_refusal_rate` jumps from 10% to 100% while `in_corpus_recall` collapses from 100% to 0%. There is no threshold in between to land on. The best available point (0.031778) gets in_corpus_recall to 100% but out_of_corpus_refusal_rate only to 10.34% — far short of `docs/PRD.md` §6's 95% target, and no other point on the curve does better on both simultaneously.

**Why this happens:** RRF fuses on rank *position*, not relevance magnitude — by construction, the top few positions across a fused list of ~50 candidates score similarly regardless of whether the top result is a strong or a barely-there match. A cross-encoder reranker exists specifically to restore a real relevance magnitude on top of that; without one, the `in_corpus?` gate has no graded signal to threshold against, only a near-binary one.

**This is now a second, independent trigger to revisit T2.2 alongside the two already listed** (corpus growth, a non-torch reranking option) — and it's a stronger one, because it's measured against the real corpus rather than anticipated. The honest characterization of where this leaves the product: retrieval currently cannot support a well-calibrated `in_corpus?` gate at production quality without either (a) a working reranker, (b) a larger corpus that gives RRF more positions to spread scores across, or (c) a different confidence signal entirely (e.g. the raw dense cosine similarity of the top result, evaluated independently of BM25 fusion — not yet tried). T4.5 should not wire the gate to 0.031778 and call it calibrated; that number is documented as the best of a bad set, not a good threshold.

**Report the resulting pair, always together:**
- **In-corpus recall** — of genuinely answerable questions, how many are correctly answered rather than wrongly refused.
- **Out-of-corpus refusal rate** — of unanswerable questions, how many are correctly refused rather than answered from the model's general knowledge.

A system that refuses everything scores perfectly on the second and zero on the first. Only the pair is meaningful.

---

## Refusal has a required shape

`refuse_gracefully` is not silence and it is never a fallback to general knowledge:

**Bad:** "I don't know."
**Bad, worse:** answering anyway from what the model already knows about Volvo or BMW generally — this is invisible unless specifically tested for, because it reads exactly like a grounded answer.
**Good:** "That's not something I have in the documents for the XC60 — no safety-rating data is loaded for this model. Worth checking the official rating directly before answering that one."

Enforced by `no_answer_outside_corpus` in `guardrails/rules.py` — full rule detail in `docs/GUARDRAILS.md`.

---

## Single generation path — every intent class, real LLM narration

**Superseded decision:** earlier drafts of this system templated SPEC-classified responses (retrieve a value, render through a fixed sentence, no free generation) to protect against numeric hallucination. This has been dropped in favour of natural generation for every response, to keep the unified chat interface consistent in voice — a mix of templated and generated replies read as inconsistent, which undermines the point of a single chat surface.

**This moves the numeric-fidelity risk from generation-time prevention to verification-time detection, and `verify_grounding` must be strengthened to cover it explicitly:**

- Extract every number/unit pair from the generated response (dimensions, prices, torque figures, whatever the query touched).
- Check each against the retrieved chunk's actual value. Not "close enough" — exact match, or within an explicitly stated tolerance for anything legitimately approximate (e.g. rounded acceleration figures if the source itself rounds).
- A numeric mismatch is a grounding violation: regenerate once, refuse on a second failure — same mechanism as an uncited claim.

**Report numeric fidelity as its own metric**, separate from the general hallucinated-fact rate — it's a distinct failure mode (paraphrase drift, not fabrication) with a distinct cause, and conflating the two in one number hides which problem you actually have.

**Latency consequence, stated plainly:** every query now costs a full generation call, including simple spec lookups that previously bypassed the model entirely. This is a real tradeoff made for response consistency, not a hidden regression — report per-intent-class latency honestly in `EVALS.md`, and lean on caching and streaming (see below) rather than reintroducing a template shortcut to hit the budget.

---

## Guardrail visibility inside chat

Since the interface is one unified chat surface (see `docs/PRD.md` §4), citations and "what not to claim"/concession content must stay a **visually distinct part of the rendered response** — a specific sentence structure, a callout, an inline source marker — not dissolve into generic conversational prose where it can be skimmed past. This is a rendering requirement for whoever builds the chat UI, not just a generation-time concern.

---

## Evals

| Dataset | Purpose |
|---|---|
| `qa.jsonl` | In-corpus questions with expected answers — drives hallucinated-fact rate, citation validity, in-corpus recall, and **numeric fidelity rate** (does every number in the response exactly match its retrieved source value) |
| `out_of_corpus.jsonl` | 30 unanswerable questions — drives out-of-corpus refusal rate |
| `concessions.jsonl` | 20 objections where the customer is factually right — drives honest-concession rate |
| `redteam.jsonl` | Adversarial guardrail set — drives refusal accuracy, per rule ID |

Plus RAGAS (faithfulness, answer relevancy, context precision, context recall) on the objection/comparison responses, as the standard-toolkit layer alongside the custom metrics above. Validate RAGAS itself: hand-label 30 examples, report agreement with the RAGAS judge — LLM-judged scores are noisy and unvalidated scores are just another model output.

Retrieval is evaluated **standalone**, before any end-to-end number: objection→category precision, the hybrid/rerank ablations, and the `in_corpus?` threshold sweep. This is what lets a failure be attributed to retrieval or generation specifically, rather than guessed at.
