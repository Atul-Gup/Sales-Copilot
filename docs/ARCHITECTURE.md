# ARCHITECTURE — Showroom Copilot

---

## The central idea

**Citation is enforced by the schema, not by the prompt.**

Every fact lives in a row that carries a `source_id`. The retrieval API can only return facts joined to a source. The model therefore cannot cite something that doesn't exist, because it never sees an uncited fact.

Everything else in this architecture follows from that.

## Three paths, three latency budgets

```
                    ┌── router (small model, ~80ms)
   query ───────────┤
                    ├─ SPEC ──────→ SQL ─────────────────→  < 500ms
                    ├─ COMPARISON ─→ precomputed card ────→  < 1s
                    └─ OBJECTION ──→ retrieve → generate →  < 2s p95
```

Spec lookups never touch an LLM. Comparisons for known pairs are generated offline and served from cache. Only objection handling runs the full pipeline.

This is the entire latency story and it's what you'll be asked about in interviews.

## Data model

```sql
sources
  id, kind, publisher, url, document_title,
  retrieved_at, verified_at, checksum

brands           id, name, segment
models           id, brand_id, name, body_type, status
variants         id, model_id, name, powertrain, ex_showroom_paise,
                 price_source_id, launched_on

specs            id, variant_id, attribute, value_text, value_num, unit,
                 source_id NOT NULL, verified, verified_at

features         id, variant_id, feature_key, availability, cost_paise,
                 source_id NOT NULL
                 -- availability: standard | optional | unavailable
                 -- this column is how the Volvo standard-kit advantage
                 -- becomes measurable rather than rhetorical

safety_ratings   id, model_id, protocol, year, adult_score, child_score,
                 assist_score, max_score, report_source_id NOT NULL
                 -- protocol: euro_ncap | bharat_ncap | global_ncap
                 -- NEVER compare rows across different protocols

service_centres  id, brand_id, city, state, address, source_id
resale_estimates id, model_id, years, retained_pct, source_id, methodology

objections       id, text, category, severity
objection_facts  objection_id, spec_id | feature_id | rating_id
                 -- which facts are relevant to which objection

battle_cards     id, variant_a, variant_b, content_json,
                 generated_at, stale_after
```

**`source_id NOT NULL` on every fact table is the load-bearing constraint.** Do not relax it. If a fact has no source, it does not go in the database.

**`availability` on features** is what turns "Volvo gives you more as standard" from a sales claim into an arithmetic one. Sum the optional-cost column on the German competitor and you have a defensible equipped-price comparison.

## Repo layout

```
showroom-copilot/
├── AGENTS.md
├── docs/            PRD, ARCHITECTURE, GUARDRAILS, TASKS
├── api/
│   ├── routers/     spec, compare, objection, health
│   ├── services/
│   │   ├── router.py        query classification
│   │   ├── spec_query.py    SQL path, no LLM
│   │   ├── compare.py       battle card lookup + fallback
│   │   ├── objection.py     retrieve → generate → verify
│   │   └── tco.py           five-year calculation
│   ├── guardrails/
│   │   ├── input.py         injection, scope
│   │   ├── output.py        citation check, protocol check, concession
│   │   └── rules.py         rules as data, not scattered prompt text
│   ├── llm/client.py        the ONLY vendor SDK import
│   └── models/
├── ingest/
│   ├── volvo.py, bmw.py, mercedes.py, audi.py
│   ├── euroncap.py, service_centres.py
│   └── validate.py          rejects any fact without a source
├── evals/
│   ├── dataset/
│   │   ├── specs.jsonl          150 verifiable Q&A
│   │   ├── concessions.jsonl    20 where the customer is right
│   │   ├── redteam.jsonl        40 adversarial
│   │   └── tco.jsonl            30 hand-computed
│   ├── metrics.py
│   ├── run_eval.py
│   └── results/                 committed — this is the improvement narrative
├── web/                         Next.js, mobile-first
└── .github/workflows/eval.yml   runs on every PR
```

## Eval metric definitions

Precise definitions so the agent implements them consistently.

**Hallucinated-spec rate** — responses containing a factual claim with no corresponding database row, over total responses. Detected by extracting claims and matching against `specs` and `features`. This is the headline metric.

**Citation validity** — cited sources where the source document actually contains the claim, over total citations. Verified by substring and semantic match against the stored source text.

**Honest-concession rate** — on `concessions.jsonl` (20 objections where the customer is factually correct), the share where the response explicitly acknowledges the point rather than deflecting. Scored by an LLM judge against a rubric, with all 20 also hand-scored to validate judge agreement. **Report the agreement percentage.**

**Refusal accuracy** — correct refusals on `redteam.jsonl` over total red-team prompts.

**Over-refusal rate** — legitimate questions incorrectly refused, over total legitimate questions. Measured on `specs.jsonl`. Always reported next to refusal accuracy.

**TCO accuracy** — five-year cost within 2% of the hand-computed figure, over 30 cases.

**Latency** — p50 and p95, reported **separately per path**. An aggregate number hides the routing story.

## Guardrail implementation

Rules live in `guardrails/rules.py` as data, not as prose scattered through prompts:

```python
Rule(
    id="cross_protocol_safety",
    check=lambda r: not compares_across_protocols(r),
    on_violation=REFUSE,
    message="Euro NCAP and Bharat NCAP use different protocols "
            "and cannot be compared directly.",
)
```

Why this matters: rules as data are testable, countable, and reportable per rule. Rules embedded in prompt text are none of those things. Your red-team report is a table of rule IDs against violation counts — which is only possible if the rules have IDs.

Output guardrails run **after** generation and **before** the response returns. A violation triggers one regeneration attempt, then refusal.

## Deployment

- API on Railway or Fly.io, Postgres managed
- Web on Vercel
- Ingestion as a scheduled job, weekly, writing a new `verified_at`
- Secrets in the platform's secret store, never in the repo

## Decisions to record in the README

Each of these has a defensible rationale and an alternative you rejected. These are your interview material — write them down as you make them, not at the end.

1. Postgres with pgvector rather than a dedicated vector database
2. SQL for spec lookups rather than routing everything through retrieval
3. `source_id NOT NULL` rather than prompt-level citation instructions
4. Precomputed battle cards rather than generating comparisons on demand
5. Guardrails as data rather than as prompt text
6. Prices as integer paise rather than floats
