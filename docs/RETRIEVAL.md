# RETRIEVAL — Showroom Copilot

How retrieval and generation work. Supersedes the retrieval sketch in `ARCHITECTURE.md`.

The one-line summary for an interview: **two retrieval tracks, routed by query type, with the objection track built as a LangGraph cycle because it genuinely has one.** Plain SQL where control flow is a straight line; a framework only where it earns its place.

---

## The three tracks (Adaptive RAG)

A classifier routes each query to the cheapest path that can answer it correctly. This pattern has a name now — adaptive RAG — but it's just: don't run a language model when a database query will do.

```
query → router ─┬─ SPEC       → SQL over fact rows          (no LLM, no retrieval)
                ├─ COMPARISON → precomputed battle card     (no LLM at serve time)
                └─ OBJECTION / → LangGraph RAG cycle         (hybrid retrieval + generate + verify)
                   DOCUMENT
```

The interview point is the routing decision itself: most "RAG systems" force every query through one pipeline. Yours routes by what the query needs. That's the judgment worth demonstrating.

---

## Two corpora, two retrieval mechanics

The mistake in the earlier design was treating fact rows as the only retrieval target. There are actually two very different bodies of knowledge here, and they need different retrieval:

### Corpus A — structured facts (rows)
Specs, features, prices, safety scores, service centres. Retrieval unit is a **typed row with a `source_id`**. Selection is a SQL join off the matched objection category. Exact, verifiable, no similarity threshold.

### Corpus B — narrative documents (chunks)
Warranty terms, service-plan documents, Euro NCAP full reports, owner's manuals, official brochures. Long prose where the answer is a passage, not a field. This is where classic document RAG earns its place.

Example queries that need Corpus B:
- "What's covered under the extended warranty for the battery pack?"
- "Does the service plan include brake pads?"
- "What did the Euro NCAP report actually say about the child occupant test?"

These are real questions consultants get, and none of them is a field lookup.

**Why this split matters:** it lets you honestly say you built both structured retrieval and document RAG, and — more importantly — that you knew which to use where. Chunking the spec sheet would have destroyed verifiability; not chunking the warranty PDF would have made it unanswerable.

---

## Corpus B ingestion

```
PDF → layout-aware parse → semantic chunking → dense + sparse index → pgvector + BM25
```

- **Parsing:** layout-aware, because warranty and NCAP docs have tables and multi-column layouts that naive text extraction scrambles. Note in the README if a particular doc type defeated the parser — that's an honest limitation, not a failure.
- **Chunking:** semantic, not fixed-size. Split on section boundaries so a warranty clause stays intact. Record `document_title`, `section`, `page` on every chunk so citations point somewhere a consultant can verify.
- **Every chunk carries a `source_id`**, same rule as the fact rows. A chunk with no traceable source does not get indexed.

---

## Hybrid retrieval (Corpus B)

Dense embeddings alone fail on this corpus because it's full of exact-match tokens: variant names ("XC60 B5 Plus Dark"), engine codes ("xDrive20i"), protocol years ("Euro NCAP 2022"). Semantic similarity blurs those; keyword search matches them exactly.

```
query
  ├─ dense retrieval (pgvector, cosine)     → top 25
  ├─ sparse retrieval (BM25)                → top 25
  └─ reciprocal rank fusion                 → merged top 50
```

Reciprocal rank fusion because it needs no score normalisation between the two retrievers — it fuses on rank position. Published comparisons on this kind of mixed corpus put hybrid recall near 0.91 against ~0.72 for sparse alone. You have a concrete reason to use it, which is the answer you want when asked "why hybrid?"

**Report the ablation.** Dense-only vs sparse-only vs hybrid on your labelled retrieval set. That table is worth more than the feature itself, and it proves you measured rather than cargo-culted.

---

## Reranking (Corpus B) — a measured trade-off

```
fused top 50 → cross-encoder reranker → top 5 → into generation context
```

Reranking scores each candidate against the query with a heavier cross-encoder. Reported gains of 15–30% on context precision, at a latency cost of a few hundred milliseconds.

**This is a real decision, not a default.** You have a 2-second p95 budget. So:

1. Measure context precision with and without reranking
2. Measure the added latency
3. Decide per track, and write down the decision

The honest interview answer — "reranking added 18% context precision for 240ms; I kept it on the objection path because it had headroom and dropped it on the document path because that one was already at budget" — demonstrates exactly the cost-awareness that separates production engineers from tutorial-followers. Whatever you actually measure, report it.

---

## The objection path as a LangGraph cycle

This path is a graph with a loop, which is the reason to use LangGraph here and nowhere else. A chain can't express "verify, and if it fails, go back and regenerate."

```
                    ┌───────────────┐
                    │  classify_    │
                    │  objection    │  → category + confidence
                    └──────┬────────┘
                           │
                  confidence < threshold?
                     │yes         │no
                     ▼            ▼
              ┌──────────┐   ┌─────────────┐
              │ abstain  │   │  retrieve   │  hybrid + rerank
              │ (generic │   │  facts +    │  (Corpus A join +
              │ guidance)│   │  documents  │   Corpus B chunks)
              └──────────┘   └──────┬──────┘
                                    ▼
                            ┌──────────────┐
                            │  generate    │  3 blocks:
                            │  response    │  true / framing / don't-claim
                            └──────┬───────┘
                                   ▼
                            ┌──────────────┐
                            │  verify_     │  every claim ↔ retrieved context
                            │  grounding   │  + guardrail rules
                            └──────┬───────┘
                                   │
                          violation found?
                         │yes            │no
                    (attempts<1)          ▼
                         │            ┌────────┐
                         ▼            │ return │
                  back to generate    └────────┘
                         │
                    (attempts==1)
                         ▼
                    ┌────────┐
                    │ refuse │
                    └────────┘
```

### Nodes

| Node | Does | Notes |
|---|---|---|
| `classify_objection` | Free-text → category + confidence | Small model. This is the Corpus A retrieval trigger |
| `abstain` | Low-confidence fallback | Forcing a category produces confidently wrong framing. Abstaining is correct behaviour |
| `retrieve` | Hybrid retrieval, both corpora | SQL join for facts, hybrid+rerank for documents |
| `generate` | Three-block response | The prompt is yours; version it |
| `verify_grounding` | Claim-by-claim check + guardrails | The loop's condition. This is the whole point |
| `refuse` | Decline with reason | Reached only after one failed regeneration |

### Why this specifically justifies LangGraph

- **It's a cycle**, not a chain. `verify_grounding → generate → verify_grounding` is a loop with a counter.
- **State is explicit** — attempts, retrieved context, violations — and passed between nodes.
- **Checkpointing gives you traces for free**, which feeds Phase 8 observability. Every run is a replayable graph execution.

Keep spec and comparison paths as plain functions. If asked why they're not in LangGraph: because they have no branches or loops, and wrapping a straight line in a graph framework is complexity for its own sake. That contrast is the answer that lands.

---

## Grounding verification — the part that matters most

`verify_grounding` is where hallucination actually gets stopped, and it's the differentiated engineering:

1. Extract atomic claims from the generated response (structured LLM call)
2. For each claim:
   - Numeric/spec claim → match against the retrieved **fact rows** (Corpus A), with tolerance
   - Narrative claim → match against the retrieved **chunks** (Corpus B), semantic + span check
3. Any unmatched claim → violation → loop back to `generate` once → `refuse`

Anyone can retrieve and generate. Verifying every claim against the retrieval set *after* generation, then refusing rather than shipping an unsupported claim, is what makes the hallucination number real. Lead with this.

---

## Evaluation

Two layers: standard metrics to prove fluency, custom metrics to prove judgment.

### Layer 1 — RAGAS (standard, proves fluency)

Run on the objection and document tracks:

| Metric | Measures | Target |
|---|---|---|
| Faithfulness | Answer sticks to retrieved context (hallucination) | > 0.9 |
| Answer relevancy | Answer addresses the question | > 0.85 |
| Context precision | Retrieved chunks are relevant | > 0.8 |
| Context recall | All needed context was retrieved | > 0.8 |

**Caveat to state in the writeup:** RAGAS scores are LLM-judged and noisy. Hand-label 30 examples, compute agreement with the RAGAS judge, and report that agreement as part of the result. An eval you didn't validate is just another model output.

**Production rule worth citing:** if faithfulness drops, fix retrieval before touching the prompt. Hallucination is usually wrong context retrieved, not the model inventing from nothing.

### Layer 2 — custom metrics (proves judgment)

These are the ones no framework ships and no other candidate has:

- **Hallucinated-spec rate** — from `verify_grounding`, the headline number
- **Honest-concession rate** — on the 20 cases where the customer is right
- **Cross-protocol refusal** — Euro NCAP vs BNCAP never compared
- **Over-refusal rate** — reported beside refusal accuracy, always

### Layer 3 — retrieval, evaluated alone

Before any end-to-end number:

- **Objection→category precision@1** on 60 labelled objections
- **Hybrid ablation** — dense vs sparse vs hybrid, recall and precision
- **Rerank ablation** — context precision and latency, with and without
- **Fact recall** — did the join surface every fact the answer needed

Measuring retrieval separately is what lets you say "this failure was retrieval, not generation" in week 9. Without it you're guessing.

---

## Tooling

| Concern | Choice | Why |
|---|---|---|
| Orchestration | LangGraph | The objection cycle. Nowhere else |
| Vector + sparse | pgvector + a BM25 extension | One database. No separate vector store to justify |
| Reranker | cross-encoder (hosted or local) | Measured trade-off, per track |
| RAG eval | RAGAS | The field-standard metrics |
| Tracing | LangGraph checkpoints + structlog | Traces fall out of the graph for free |

**Still no dedicated vector database.** pgvector handles this corpus size comfortably. "I didn't need Pinecone and here's the corpus size that told me so" remains a stronger answer than adding it. Don't add infrastructure the data doesn't demand.

---

## What changes in TASKS.md

Phase 4 expands. Replace the old T4.2 with:

- **T4.2a** Corpus B ingestion — parse, semantic-chunk, index warranty / service-plan / NCAP-report / manual PDFs. Every chunk sourced.
- **T4.2b** Hybrid retrieval — dense + BM25 + reciprocal rank fusion. Ablation on the labelled set.
- **T4.2c** Reranking — cross-encoder, top-50 → top-5. Measure precision gain and latency cost per track; decide and document.
- **T4.3** Objection generation as LangGraph nodes (`classify`, `retrieve`, `generate`).
- **T4.4** `verify_grounding` as the cyclic node, plus the concession rule.
- **T4.6** (new) RAGAS harness + the 30-example judge-agreement check.

Phase 3's retrieval evals (Layer 3 above) still come **before** any of this. Build the ruler first.
