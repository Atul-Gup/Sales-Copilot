# TASKS — Showroom Copilot

Work **one task at a time**. Each is scoped to a single agent session because Antigravity context resets between sessions. Do not batch.

Mark tasks `[x]` as they complete. If a task turns out bigger than one session, split it in this file first.

---

## Phase 1 — Foundation (weeks 1–2)

- [x] **T1.1** Scaffold repo per `docs/ARCHITECTURE.md`. FastAPI app, health endpoint, Postgres via docker-compose, pytest running, pre-commit with ruff and mypy. Done when `pytest` and `docker-compose up` both work from clean.
- [x] **T1.2** SQLAlchemy models + Alembic migration for the full schema. Enforce `source_id NOT NULL` on `specs`, `features`, `safety_ratings`. Add a test proving a fact cannot be inserted without a source.
- [x] **T1.3** `ingest/validate.py` — rejects any record lacking a source, an unknown source kind, or a `verified_at` older than the threshold. Test with deliberately bad fixtures.
- [x] **T1.4** Ingest Volvo India lineup at **variant level** — variants, prices, specs, features with `availability`. Start from official spec sheet PDFs. Manual entry is acceptable; correctness beats automation here.
  - No source PDF publishes an ex-showroom price; `variants.ex_showroom_paise`/`price_source_id` are now nullable (migration `711e98bf4f5b`) and both are `null` for every ingested variant. Backfill when a priced source is available.
- [x] **T1.5** Ingest direct competitors: BMW, Mercedes-Benz, Audi. One competitor per Volvo model minimum. Same variant-level detail.
  - XC60 has all three (X3, GLC, Q5). **EX30 has zero** — `competitors/bmw-ix1-specs.pdf` turned out to be the BMW X1 LWB (petrol ICE), not the iX1 EV CORPUS.md names as its sole competitor; held rather than mis-ingested. Needs the correct iX1 spec sheet before EX30 gets a competitor row.
- [x] **T1.6** Ingest Euro NCAP ratings. `protocol='euro_ncap'` on every row. No BNCAP rows exist for Volvo India — if the ingest produces one, it's a bug.
  - 4 of 6 ratings ingested: XC60 (expired, the 2017 D4 diesel landmine), EX30, GLC, Q5. **X3 and iX1 have no rating** — the corpus's `bmw-x3` and `bmw-ix1` euroncap files turned out to be the 3 Series sedan and the (large) iX, not X3/iX1; held rather than mis-attributed. Also extended `safety_ratings` schema: added `tested_variant`, `status` (current/expired), `vru_score` (all required by `docs/CORPUS.md`, absent from the original T1.2 schema); dropped `max_score`, which turned out not to correspond to anything Euro NCAP publishes.
- [ ] **T1.7** Ingest service centre locations for all four brands from official locators.

## Phase 2 — Spec path (weeks 3–4)

- [ ] **T2.1** `services/spec_query.py` — structured lookup, pure SQL, no LLM. Returns facts with sources attached. Test that the response type cannot represent an uncited fact.
- [ ] **T2.2** `services/router.py` — classify query as SPEC, COMPARISON, or OBJECTION. Small model or classifier. Target under 100ms. Test on 50 labelled queries.
- [ ] **T2.3** `/spec` and `/compare` endpoints. Compare returns a structured diff with sources per row.
- [ ] **T2.4** Equipped-price comparison — sum `availability='optional'` costs on the competitor to produce a like-for-like figure against Volvo's standard kit. This is the core value proposition; get it right.
- [ ] **T2.5** Battle card generation, offline, for the main Volvo-versus-German pairs. Store in `battle_cards` with `stale_after`.

## Phase 3 — Evals (week 5) ⚠️ do not skip

**Build this before the objection layer.** Optimising without measurement produces no improvement narrative, and "I tried a better prompt and it felt better" is the worst possible interview answer.

- [ ] **T3.1** `evals/dataset/specs.jsonl` — 150 verifiable questions with answers from ingested data. Cover Volvo and all three competitors, dimensions, features, safety, price.
- [ ] **T3.2** `evals/dataset/concessions.jsonl` — 20 objections where the customer is factually right. Service network, resale, brand, waiting period.
- [ ] **T3.3** `evals/dataset/redteam.jsonl` — 40 prompts per `docs/GUARDRAILS.md`, each tagged with `expected_rule`.
- [ ] **T3.4** `evals/dataset/tco.jsonl` — 30 hand-computed five-year cases. Compute by hand and record the working.
- [ ] **T3.5** `evals/metrics.py` — implement every metric per the definitions in `ARCHITECTURE.md`. Hallucinated-spec rate, citation validity, honest-concession, refusal accuracy, over-refusal, TCO accuracy, latency per path.
- [ ] **T3.6** `evals/run_eval.py` + `results/` output. Run against the current spec path. **Commit the baseline** — this is version 1 of your improvement narrative.
- [ ] **T3.7** CI workflow running evals on every PR and posting the metric diff.

## Phase 4 — Objection handling (weeks 6–7)

- [ ] **T4.1** `llm/client.py` — provider-agnostic wrapper. Retries, timeouts, token and cost logging. The only file importing a vendor SDK.
- [ ] **T4.2** Retrieval for objections — pgvector over objection-relevant facts, joined to sources. Evaluate retrieval precision **standalone** before end-to-end.
- [ ] **T4.3** Objection response generation in three blocks: what's true, how to frame it, what not to claim.
- [ ] **T4.4** Implement `must_concede`. Detect known-weakness objections and enforce the response shape from `GUARDRAILS.md`. Run against `concessions.jsonl` and report the rate.
- [ ] **T4.5** `services/tco.py` — five-year calculation with an explicit assumptions panel. Never present as guaranteed.

## Phase 5 — Guardrails (week 8)

- [ ] **T5.1** `guardrails/rules.py` — every rule from `GUARDRAILS.md` as data with an ID. One test per rule.
- [ ] **T5.2** Input guardrails — injection stripping, scope check, customer-facing refusal.
- [ ] **T5.3** Output guardrails — citation check, protocol check, disparagement check, service overstatement check. Runs post-generation, pre-response, one regeneration attempt then refuse.
- [ ] **T5.4** Full red team run. **Report per rule ID, before and after.** Fix every violation on `cross_protocol_safety`, `service_overstatement`, `must_concede`.
- [ ] **T5.5** Measure over-refusal on `specs.jsonl`. If above 5%, the guardrails are too tight — tune and re-run both.

## Phase 6 — Latency (week 9)

- [ ] **T6.1** Instrument per-path latency. p50 and p95 separately for spec, comparison, objection.
- [ ] **T6.2** Cache battle cards and frequent spec queries. Invalidate on `verified_at` change.
- [ ] **T6.3** Stream objection responses. First token is what matters when someone is standing there.
- [ ] **T6.4** Optimise until p95 is under 2s on the objection path. Document what worked and what didn't — the failed attempts are interview material too.

## Phase 7 — Interface (week 10)

- [ ] **T7.1** Next.js app, mobile-first. Consultants use phones, not laptops.
- [ ] **T7.2** Comparison view — sources visible on every row, not hidden behind a tooltip.
- [ ] **T7.3** Objection view — the "what not to claim" block must be visually prominent, not a footnote.
- [ ] **T7.4** Deploy. API on Railway or Fly, web on Vercel, live URL.

## Phase 8 — Observability and write-up (weeks 11–12)

- [ ] **T8.1** Structured logging on every LLM call — model, tokens, latency, cost, guardrails fired.
- [ ] **T8.2** Internal dashboard: query volume by path, cost per day, refusal and concession rates over time.
- [ ] **T8.3** `EVALS.md` — the public results table, version by version, with the failure taxonomy.
- [ ] **T8.4** `SECURITY.md` — red team results per rule, before and after.
- [ ] **T8.5** README with the six architecture decisions from `ARCHITECTURE.md`, each with the alternative you rejected.
- [ ] **T8.6** 90-second demo video. Show the problem, a comparison, and a concession response. Do not narrate your tech stack.

---

## Do out of band — week 3, in parallel

- [ ] **T0.1** Talk to at least one working luxury-segment sales consultant. Check whether Indore has a BMW, Mercedes, or Audi outlet; the objection taxonomy transfers. Otherwise phone a Volvo dealership in Pune or Ahmedabad.
- [ ] **T0.2** Rewrite `concessions.jsonl` and the objection categories based on what they actually said. Expect to be wrong about what consultants struggle with.
- [ ] **T0.3** Record what you learned in the README.

This is the highest-value item in the file and the easiest to skip.

---

## Working notes for the agent

- Read `AGENTS.md` before every session — context does not persist
- One task per session. Report eval deltas in the summary
- Never mark a task done without running it
- If a task reveals the plan is wrong, update this file before continuing
