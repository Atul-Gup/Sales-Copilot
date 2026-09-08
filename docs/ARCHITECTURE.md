# ARCHITECTURE — Showroom Copilot

Supersedes the structured-fact-table / two-corpus design from earlier drafts.

---

## The central idea, restated for this version

**The system may only state what a retrieved document supports, and must say so plainly when nothing does.**

There is no structured fact database to query directly anymore — no SQL fast path, no `specs`/`features`/`safety_ratings` tables. The corpus is a small set of reformatted product documents, chunked and embedded. Every answer, including simple spec lookups, goes through retrieval. What varies is how the response gets generated afterward — see the templated-vs-generated split below — not whether retrieval happens.

## One retrieval path, one gate that matters

```
                    ┌── classify_intent (SPEC | COMPARISON | OBJECTION)
                    │    used to pick prompt/template, NOT to skip retrieval
   query ───────────┤
                    └─ retrieve (hybrid: dense + BM25 + RRF, reranked)
                           │
                    in_corpus? (calibrated threshold, not a default cutoff)
                       │no                    │yes
                       ▼                       ▼
                  refuse_gracefully       generate
                  (name what's missing)   (template for SPEC,
                                            LLM narration for
                                            COMPARISON/OBJECTION)
                                                │
                                          verify_grounding
                                                │
                                    violation? loop once → refuse
                                                │no
                                                ▼
                                       render (citations + "don't
                                       claim" content stay visible
                                       inside the chat response)
```

`in_corpus?` is the most important node in this graph. Retrieval will always return its nearest top-k chunks, whether or not any of them actually answer the question — cosine similarity doesn't know the difference between "relevant" and "least irrelevant." The threshold must be calibrated against labelled in-corpus and out-of-corpus question sets, not left at a library default. Full detail in `docs/RETRIEVAL.md`.

## Data model

```sql
sources
  id, kind, publisher, document_title, retrieved_at, checksum
  -- kind: 'product_document' | 'service_centre_list'

chunks
  id, source_id NOT NULL, document_id, text, embedding vector(1536),
  section, page
  -- text is stored alongside the vector so retrieval can cite and
  -- render the actual passage, not just locate it

service_centres
  id, brand, city, state, address, source_id NOT NULL
  -- structured, separate from the chunked corpus; queried by direct
  -- lookup, not retrieval

models        id, brand, name, status
              -- e.g. Volvo XC60, BMW X3 — no separate variant/spec tables;
              -- facts about a model live in its document's chunks
```

**`source_id NOT NULL` is still enforced everywhere.** Collapsing to one corpus type didn't relax the citation discipline — it just means every fact traces to a chunk instead of to a structured row.

Note what's gone from the earlier schema: `specs`, `features`, `safety_ratings`, `resale_estimates`, `objection_facts`, `battle_cards`. None of these exist. If a future session proposes recreating them, that's a sign the corpus scope has grown back toward structured data and `docs/CORPUS.md` needs updating first.

## Repo layout

```
showroom-copilot/
├── AGENTS.md
├── docs/            PRD, ARCHITECTURE, GUARDRAILS, CORPUS, RETRIEVAL, TASKS
├── api/
│   ├── routers/     chat (single endpoint), health
│   ├── services/
│   │   ├── router.py         intent classification (prompt selection only)
│   │   ├── retrieve.py       hybrid retrieval + rerank + in_corpus gate
│   │   ├── generate.py       templated (SPEC) vs LLM narration (COMPARISON/OBJECTION)
│   │   └── verify.py         grounding check, the LangGraph cycle
│   ├── guardrails/
│   │   ├── input.py          injection, scope
│   │   ├── output.py         citation check, concession check, refusal check
│   │   └── rules.py          rules as data — see GUARDRAILS.md
│   ├── llm/
│   │   ├── client.py         the ONLY vendor SDK import (chat model)
│   │   └── embeddings.py     OpenAI text-embedding-3-small, cached
│   └── models/
├── ingest/
│   ├── product_docs.py       parse, chunk, embed the Word/PDF corpus
│   ├── service_centres.py    structured spreadsheet ingest
│   └── validate.py           rejects anything without a source
├── evals/
│   ├── dataset/
│   │   ├── qa.jsonl              in-corpus questions with expected answers
│   │   ├── out_of_corpus.jsonl   30 questions with no supporting document
│   │   ├── concessions.jsonl     20 objections where the customer is right
│   │   └── redteam.jsonl         adversarial guardrail set
│   ├── metrics.py
│   ├── run_eval.py
│   └── results/                   committed — the improvement narrative
├── web/                            single chat interface, mobile-first
└── .github/workflows/eval.yml
```

## Single generation path, strengthened verification

All intent classes generate through the LLM — there is no templated-vs-generated split. This was a deliberate reversal from an earlier draft: templating SPEC responses protected numeric fidelity at generation time, but produced an inconsistent voice across a unified chat interface, which defeats the point of having one.

The numeric-fidelity protection moved downstream into `verify_grounding` instead: every number/unit the response states is checked against its retrieved source value, exact match (or an explicit stated tolerance), and a mismatch is a grounding violation — same regenerate-once-then-refuse mechanism as an uncited claim. **This trades a generation-time guarantee for a verification-time check**, and the honest cost is that every query, including simple spec lookups, now makes a full generation call — see the latency section below and report per-intent-class numbers rather than an aggregate.

## Eval metric definitions

- **Hallucinated-fact rate** — responses containing a claim with no corresponding retrieved chunk, over total responses. Headline metric.
- **Numeric fidelity rate** — of numbers/units stated in a response, the share that exactly match their retrieved source value. Distinct from hallucinated-fact rate: this catches paraphrase drift (483L restated as "around 480L") rather than fabrication from nothing, and it exists specifically because there's no template anchoring numeric output anymore.
- **In-corpus recall** — of questions genuinely answerable from the documents, the share correctly answered rather than refused.
- **Out-of-corpus refusal rate** — of questions with no supporting document, the share correctly refused rather than answered from general knowledge. Report with recall, never alone — a system that refuses everything scores perfectly on one and zero on the other.
- **Citation validity** — cited passages that actually contain the claim, over total citations.
- **Honest-concession rate** — on `concessions.jsonl`, the share where the response explicitly acknowledges a valid customer objection rather than deflecting. LLM-judged, validated against hand-labels, agreement rate reported.
- **Refusal accuracy / over-refusal rate** — on `redteam.jsonl` and `qa.jsonl` respectively, always reported as a pair.
- **Latency** — p50/p95, reported per query classification, not aggregated.

## Guardrails as data

Rules live in `guardrails/rules.py`, each with an ID, a check, an action, and a test. Not prose scattered through prompts — see `docs/GUARDRAILS.md` for the current rule set, headlined by `no_answer_outside_corpus`.

## Deployment

API on Railway or Fly, Postgres managed with pgvector, web on Vercel. Ingestion is a manual/scheduled step against `data/sources/products/` — see `docs/CORPUS.md` for exactly what's in scope.

## Decisions to record in the README

1. Single document corpus over structured fact tables + separate narrative corpus — the documents were already well-formatted; two layers added complexity without adding accuracy.
2. Closed-book refusal (`no_answer_outside_corpus`) over broader, less-verified coverage — a smaller corpus the system stays honest about beats a broader one it might silently supplement from training data.
3. Calibrated `in_corpus?` threshold over a default similarity cutoff, and why that calibration mattered in practice.
4. Full LLM generation for every response, over an earlier templated-SPEC-path draft — chosen for consistent voice across the unified chat interface, with the resulting numeric-fidelity risk covered by strengthening `verify_grounding` rather than by templating around it. State the latency cost this added honestly.
5. Unified chat interface over separate comparison/objection/spec screens, and how guardrail visibility was preserved inside natural-language responses.
6. EX30 shipping with zero competitors rather than a mismatched one — a data-honesty decision, not an oversight.
