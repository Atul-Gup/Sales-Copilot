# TASKS — Showroom Copilot

Supersedes the structured-database task list. Work **one task at a time** — Antigravity context resets between sessions, and `AGENTS.md` is the only thing guaranteed to persist. Mark `[x]` as tasks complete.

---

## Phase 0 — Corpus (parallel, do first)

- [ ] **T0.1** Finish the five reformatted product documents (Volvo XC60, Volvo EX30, BMW X3, Mercedes GLC, Audi Q5) per `docs/CORPUS.md`. This is manual writing/formatting work, not an agent task — do it yourself.
- [ ] **T0.2** Place them in `data/sources/products/<brand>/`. Archive (don't delete) the old spec sheets, Euro NCAP PDFs, and warranty PDF to `data/sources/_archive/`. Delete the mislabelled BMW "iX1" file (it's actually an X1) or rename it clearly and move it to archive.
- [ ] **T0.3** Talk to at least one working luxury-segment sales consultant — check whether a BMW/Mercedes/Audi dealer exists locally, since the objection taxonomy transfers regardless of badge. Rewrite `concessions.jsonl` (T3.2) around what they actually say. Highest-value item in this file; do it before Phase 4.

---

## Phase 1 — Foundation

- [x] **T1.1** Scaffold repo: FastAPI app, Postgres + pgvector via docker-compose, pytest, ruff, mypy. *(Already complete.)*
- [x] **T1.2** Schema per `docs/ARCHITECTURE.md`: `sources`, `chunks` (with `vector(1536)`), `service_centres`, `models`. No `specs`/`features`/`safety_ratings` tables — those belonged to the earlier design. Enforce `source_id NOT NULL` on `chunks` and `service_centres`. Test that a chunk cannot be inserted without a source.
  - Found the repo held a full previous implementation against the old structured-fact design (specs/features/safety_ratings/battle_card tables, per-brand ingest scripts, an objection LangGraph pipeline, spec/compare routers, most of `evals/`). Removed it all; rebuilt `api/models/` to exactly this schema (`Source`, `Chunk`, `ServiceCentre`, `CityAlias`, `Model`) and wrote a fresh initial migration (no live Postgres in this sandbox to autogenerate against). Kept what didn't depend on removed tables: guardrail rules/input/output checks, the intent-classifier router, `ingest/validate.py`, `api/routers/health.py`. `pytest api ingest` → 141 passed at the time; ruff/mypy clean.
- [x] **T1.3** `ingest/validate.py` — rejects any record without a source, or any document not named in `docs/CORPUS.md`. Test with fixtures including a document deliberately not on the list.
  - Added `ALLOWED_PRODUCT_DOCUMENT_TITLES` (the five titles from `docs/CORPUS.md`, verbatim) and a check in `validate_fact_record` for `kind == "product_document"`. 145 passed; ruff/mypy clean.
- [x] **T1.4** `ingest/product_docs.py` — parse the five documents, semantic-chunk (don't split mid-fact), embed via `llm/embeddings.py` (OpenAI `text-embedding-3-small`, cached), store in `chunks`. Report chunk count and any parsing failures per document.
  - **Blocker, worked around per your call:** `data/sources/products/Mercedes/` is empty — the GLC document (T0.1) hasn't been added. Built and tested against the 4 documents that exist; GLC is wired into `DOCUMENTS` at its expected path and will ingest automatically once added. Each document is organised into numbered sections (one label/value fact table each) — a section is the chunking unit, split further only past 1500 chars. Chunk counts: XC60 13, EX30 12, X3 12, Q5 12. 152 passed (fake-embedder tests, no API key needed); ruff/mypy clean.
- [x] **T1.5** `ingest/service_centres.py` — the T1.7-equivalent spreadsheet ingest, brand/city/state/address, `source_id NOT NULL`. Normalise city names (Bangalore/Bengaluru, Gurgaon/Gurugram) and record aliases.
  - Already existed from T1.2's rewiring but had no test coverage — added `ingest/test_service_centres.py`. Verified against the real spreadsheet: 24 rows → 22 centres (2 correctly excluded per documented reasoning), 4 sources, 3 city aliases seeded and applied. 157 passed; ruff/mypy clean.

---

## Phase 2 — Retrieval

- [x] **T2.1** Hybrid retrieval: dense (pgvector) + BM25 + reciprocal rank fusion. Query against the chunked corpus.
  - Built `api/services/retrieve.py` (the file `docs/ARCHITECTURE.md`'s repo layout names for this). Ranking runs in Python over the full chunk set — the corpus is small enough, and it keeps this testable against SQLite without a live pgvector index. `dense_rank` (cosine similarity, pure Python), `sparse_rank` (BM25 via `rank-bm25`), `reciprocal_rank_fusion` (fuses on rank position, no score normalisation), wired together in `hybrid_search()`. Sanity-checked end-to-end against the real ingested corpus with a hash-based fake embedder — BM25 correctly surfaced the XC60's "Dimensions & Capacity" section for a wheelbase query. Reranking (T2.2) and the `in_corpus?` gate are explicitly out of scope here. 164 passed; ruff/mypy clean.
  - Not done yet, flagged for later: the dense-vs-sparse-vs-hybrid ablation report needs `qa.jsonl` (T3.1), which doesn't exist. Revisit once Phase 3's datasets exist.
- [x] **T2.2** Reranker: cross-encoder over the fused top-50 → top-5. Measure latency added; decide whether it's worth it against the 2s budget and document the call.
  - **Decision: dropped, not built.** Full reasoning in `docs/RETRIEVAL.md`'s "Reranking decision" section. Short version: tried a real local cross-encoder via `sentence-transformers`/`torch` (both the default and CPU-only wheels), and both fail to load on this machine with a DLL init error (`WinError 1114`, `c10.dll`) — a genuine environment blocker, not a hypothetical cost. Combined with the corpus being only 49 chunks (4 of 5 documents ingested so far), a rerank over the fused top-50 would be reranking nearly the entire corpus for most queries — thin justification even without the install friction. `hybrid_search`'s fused ranking is used directly; revisit if the corpus grows or a non-torch reranking option becomes available.
  - Uninstalled `sentence-transformers`/`torch` afterward — not left as dead weight in the venv since the decision was not to use them.
- [x] **T2.3** `classify_intent` — SPEC | COMPARISON | OBJECTION. *(Already implemented pre-reset in `api/services/router.py::classify` — kept through the T1.2 rebuild since it has no model dependencies. Regex-based, precedence OBJECTION > COMPARISON > SPEC. Updated its docstring to drop the stale "SPEC never touches an LLM" reasoning now that the single-generation-path decision means every intent class goes through full LLM narration — the classifier only selects prompt style, never whether generation happens or whether retrieval runs. `api/services/test_router.py` has the required 50-labelled-query set (17 SPEC / 16 COMPARISON / 17 OBJECTION) plus a <100ms latency assertion — all passing.)*
- [x] **T2.4** Equipped-price comparison. *(Descoped, not built — checked all 5 product documents by hand and none contain pricing or an itemized standard-vs-optional equipment breakdown; each brochure explicitly disclaims exact tier/price detail ("exact standard/optional availability should be read [elsewhere]", "some equipment...may only be available at extra cost" with no itemization). Building this feature would mean fabricating figures the sources never state, which violates the closed-book discipline this whole project is built to demonstrate — the honest move is the same one already documented for the EX30 competitor gap. `no_answer_outside_corpus` refuses price/equipment-tier questions instead. Documented in `docs/CORPUS.md` and `docs/PRD.md` §5 as a named scope decision, not a silent gap.)*

---

## Phase 3 — Evals ⚠️ before Phase 4

Build the ruler before tuning generation. This is the phase most likely to be skipped and the one that produces the version-over-version results table that makes this portfolio-grade.

- [x] **T3.1** `evals/dataset/qa.jsonl` — 32 questions hand-written against the actual source PDFs (read every document by hand, no fabricated figures). *(Two adjustments from the original scope, both already-known gaps: (1) no "pricing" category — none of the five documents contain pricing data, per T2.4's descoping; questions span dimensions/powertrain/features instead. (2) only 4 of 5 models covered — Mercedes GLC's product document still hasn't been sourced (T0.1 blocker, `data/sources/products/Mercedes/` is empty), so no genuinely-answerable GLC question exists yet; add GLC entries once that file lands. Each record carries `expected_values` (value/unit/label triples) for T3.5's numeric fidelity check. `evals/dataset/test_qa.py` validates schema, id uniqueness, category allow-list, and that the model allow-list matches the 4 currently-available documents — so this test starts failing loudly, not silently, the moment GLC is added without new questions.)*
- [x] **T3.2** `evals/dataset/out_of_corpus.jsonl` — 30 questions across 7 categories: `safety_ratings`, `warranty`, `service_plan`, `on_road_pricing`, `ex30_competitor`, `glc_not_sourced`, `out_of_scope_brand`. *(One subtlety worth flagging: the EX30's own product document states "Euro NCAP 5-star rating & IIHS Top Safety Pick" as a brochure line — so a safety-rating question about the EX30 specifically is NOT a clean out-of-corpus case like every other model; `ooc_006` captures this as a mixed case (the award claim is answerable, a general-knowledge extension of it is not) rather than mislabelling it a plain refusal. Also distinguished `glc_not_sourced` (temporary — closes once T0.1 lands) from the permanent exclusions, since conflating "not sourced yet" with "permanently excluded" would be its own small dishonesty. `test_out_of_corpus.py` enforces schema and specifically asserts the EX30 safety question stays flagged as the mixed case.)*
- [x] **T3.3** `evals/dataset/concessions.jsonl` — 20 objections, built as a **provisional v1** since T0.3 (the real consultant interview) hasn't happened yet; this set is an assumption per `docs/PRD.md` §9 and should be revisited once that interview does. *(Real finding while building this: `docs/GUARDRAILS.md`'s `must_concede` rule assumed all three weakness categories — service network, resale, EX30 gap — were equally document-supported. They aren't. Fixed the rule doc and split the dataset accordingly: **service_network** (7, grounded in the actual ingested `service_centres` table, not the raw spreadsheet — one entry specifically catches that Audi's ingested count is 6, not the raw sheet's 7, because `ingest/service_centres.py` excludes an unverified Bhopal row); **resale_value** (7, hybrid concession — concede the concern, explicitly refuse any figure, since the old resale table was deleted in T1.2 and no resale document exists anywhere); **ex30_price_class_gap** (6, grounded in the documented iX1 absence, careful not to reintroduce the old "~20% more" fabricated figure that was sitting in `docs/GUARDRAILS.md`'s example text). `test_concessions.py` schema-checks the file and independently recomputes the service-centre counts from the real spreadsheet to catch drift.)*
- [x] **T3.4** `evals/dataset/redteam.jsonl` — grew from 40 to 58 entries, now with at least one entry per rule ID in `api/guardrails/rules.py` (enforced by the new `test_every_rule_has_at_least_one_redteam_entry` in `evals/dataset/test_redteam.py`). *(This surfaced two real bugs, both fixed: (1) `no_answer_outside_corpus` — described in GUARDRAILS.md as "the headline rule for this version of the product" — was missing from `rules.py`'s data table entirely, so no red-team entry could ever reference it without failing the id-exists check; added it (action REWRITE, same regenerate-once-then-refuse convention as every other REWRITE rule — its old "REWRITE, then REFUSE" phrasing in GUARDRAILS.md was just a redundant restatement of that same convention, simplified). Added 6 new `out_of_corpus_elicitation` entries (direct + framing-pressure) against it. (2) The `on_road_price` rule's action was `ANNOTATE` with two redteam entries (rt_020/rt_021) whose notes referenced `ex_showroom_paise`, a column from the pre-T1.2 schema that no longer exists — and since T2.4 confirmed no document contains pricing data at all, there is no base figure to annotate a caveat onto anymore. Changed the rule to REFUSE (in `docs/GUARDRAILS.md`, `rules.py`, `output.py`'s behavior follows automatically since it reads the rule's action, and the two dependent tests in `test_output.py`/`test_rules.py`), and fixed the stale notes. Also fixed a dangling cross-reference in rt_014 (pointed at a `concessions.jsonl` id that no longer exists after T3.3's rewrite) and a stale over-refusal example in `docs/GUARDRAILS.md` that assumed equipped-price comparison was answerable — it isn't, per T2.4. Added the remaining missing rule coverage: `uncited_claim` (3), `stale_data` (2), `no_clinical_certainty` (3), `customer_facing` (4).)*
- [x] **T3.5** `evals/metrics.py` — every metric from `docs/PRD.md` §6: `numeric_fidelity_rate`, `citation_validity_rate`, `hallucinated_fact_rate`, `in_corpus_recall`, `out_of_corpus_refusal_rate`, `honest_concession_rate`, `refusal_accuracy`, `over_refusal_rate`, `latency_by_intent`. *(Built ahead of Phase 4 on purpose, per this phase's own "build the ruler before tuning generation" banner — every function takes plain data (text, chunk strings, bools), not a pipeline object, so `evals/test_metrics.py`'s 39 synthetic-example tests can run today and `evals/run_eval.py` (T3.7) can wire the same functions to real pipeline output later unchanged. Two functions — `numeric_fidelity_rate` and `citation_validity_rate` — are explicitly heuristic (substring/word-overlap matching, not real claim-to-source entailment) and say so in their docstrings, rather than pretending to a sophistication that isn't actually implemented; both should be revisited once T4.4's real grounding-check logic exists. One real bug caught while testing: the first number-extraction regex matched digits embedded in model names ("XC60" → spurious "60", "xDrive20d" → spurious "20"), which would have silently corrupted every fidelity/citation/hallucination score on any response that names a model. Fixed by tokenizing first and requiring a whole token to be a pure number before counting it.)*
- [x] **T3.6** Calibrated the `in_corpus?` threshold: `evals/calibrate_threshold.py` ingests the real corpus with real embeddings, scores every `qa.jsonl`/`out_of_corpus.jsonl` question, sweeps every observed score as a candidate threshold, and reports the full curve in `evals/results/threshold_calibration.md`. *(RETRIEVAL.md said "sweep the reranker-score threshold," but T2.2 dropped the reranker — swept `hybrid_search_scored`'s new fused-RRF score instead (added alongside the existing `hybrid_search`, same ranking, now paired with each chunk's score). **Real finding, not just a number**: the RRF score doesn't separate in-corpus from out-of-corpus smoothly — the curve has a cliff (out_of_corpus_refusal_rate jumps 10%→100% between two adjacent scores while in_corpus_recall collapses 100%→0%), not a slope. Best available point (0.031778) clears recall (100%) but badly misses the refusal target (10.34% vs the 95% in `docs/PRD.md` §6) — documented honestly in `docs/RETRIEVAL.md` as "best of a bad set," not a calibrated threshold, with an explicit note that T4.5 should not wire the gate to this number and call it done. This is now the strongest of the three listed reasons to revisit T2.2's reranker decision, since it's measured against the real corpus rather than anticipated.)*
- [x] **T3.7** `evals/run_eval.py` + `evals/results/baseline.json` — **baseline v0, honestly partial.** Runs the retrieval gate (T3.6's threshold) and the 3 input-side guardrail rules against the real corpus; every other metric (`hallucinated_fact_rate`, `numeric_fidelity_rate`, `citation_validity_rate`, `honest_concession_rate`, the 10 output-side guardrail rules) gets `"value": null` and an explicit `"blocked_on"` reason rather than a fabricated number — none of them can be computed without Phase 4 generation, which doesn't exist yet. *(Two real T5.2 bugs found and fixed by this run, not just numbers reported: (1) `run_input_guardrails` checked `out_of_scope` before `customer_facing`, so a customer-facing draft request that didn't happen to name a specific model — "confirm today's discount" — was misreported as out_of_scope; reordered, with the reasoning in `input.py`'s docstring. (2) `_CUSTOMER_FACING_RE` only matched "draft/write ... to/for customer" phrasing, missing the adjective form ("customer-facing marketing copy"); added a pattern for it. `refusal_accuracy` on the checkable subset went from 84.62% to 100% after both fixes — regression tests added to `test_input.py`. Also discovered `evals/diff_results.py` and its test existed before but were deleted (only their `.pyc` survived in `__pycache__`) — reconstructed both from the bytecode to restore the exact JSON contract `.github/workflows/eval.yml` already depended on, rather than inventing an incompatible new one.)*
- [x] **T3.8** CI workflow — `.github/workflows/eval.yml` already existed (pre-built, like several other T5.x pieces this phase turned up) but depended on the missing `evals/diff_results.py` and a `evals/results/baseline.json` on the base branch. Both now exist; also found and fixed `pyproject.toml`'s `[tool.mypy] files` list was missing `"evals"` entirely, meaning CI's `mypy .` was silently skipping every eval file — added it, then re-ran `mypy .`/`ruff check .`/`pytest -q` exactly as CI invokes them to confirm the workflow will actually pass end to end.

---

## Phase 4 — Generation

- [ ] **T4.1** `llm/client.py` — provider-agnostic wrapper, retries, timeouts, token/cost logging.
- [ ] **T4.2** Single generation path — every intent class (SPEC, COMPARISON, OBJECTION) generates a natural-language response via the LLM over the retrieved chunks. No template branch. Prompt varies by intent class for tone/structure, but generation always happens.
- [ ] **T4.3** COMPARISON/OBJECTION generation — LLM narration over retrieved chunks. Iterate against `qa.jsonl`/`concessions.jsonl`, keep every prompt version for the v1→v4 table.
- [ ] **T4.4** `verify_grounding` as a LangGraph node — checks generated claims against retrieved chunks AND checks every number/unit stated in the response against its exact retrieved value (this replaces the numeric-safety the template used to provide — there is no other guard against paraphrase drift now). Loops to regenerate once on either kind of violation, refuses on a second failure. This is the cyclic part that justifies using LangGraph at all.
- [ ] **T4.5** `no_answer_outside_corpus` enforcement — wire the `in_corpus?` gate to `refuse_gracefully`, with the required response shape from `docs/RETRIEVAL.md`. Run against `out_of_corpus.jsonl`.
- [ ] **T4.6** `must_concede` — detect known-weakness objections, enforce the concession response shape. Run against `concessions.jsonl`, report the rate. Include the EX30-no-competitor case explicitly.

---

## Phase 5 — Guardrails

- [ ] **T5.1** `guardrails/rules.py` — every rule from `docs/GUARDRAILS.md` as data with an ID. One test per rule.
- [ ] **T5.2** Input guardrails — injection stripping, out-of-scope refusal, customer-facing refusal.
- [ ] **T5.3** Output guardrails — citation check, disparagement check, service-overstatement check. Post-generation, pre-response, one regeneration attempt then refuse.
- [ ] **T5.4** Full red team run. Report per rule ID, before and after. Fix any regression on `no_answer_outside_corpus`, `service_overstatement`, `must_concede`.
- [ ] **T5.5** Over-refusal check against `qa.jsonl`. If above 5%, the `in_corpus?` threshold or the guardrails are too tight — retune both, re-run, report both numbers together.

---

## Phase 6 — Latency

- [ ] **T6.1** Instrument per-intent-class latency (p50/p95), not aggregate.
- [ ] **T6.2** Cache retrieval results and embeddings for repeat queries.
- [ ] **T6.3** Stream generated responses.
- [ ] **T6.4** Optimise until objection-path p95 is under 2s. Document what didn't work, not just what did.

---

## Phase 7 — Interface

- [ ] **T7.1** Next.js chat interface, mobile-first, single input, single response stream. No separate comparison/objection/spec screens.
- [ ] **T7.2** Response rendering: citations and "don't claim"/concession content are visually distinct inside the chat bubble — a callout or inline marker, not dissolved into paragraph text.
- [ ] **T7.3** Refusal responses render clearly as refusals, not as a dead end — show what was checked and what to do instead.
- [ ] **T7.4** Deploy: API on Railway/Fly, web on Vercel, live URL.

---

## Phase 8 — Observability and write-up

- [ ] **T8.1** Structured logging on every retrieval, embedding, and generation call.
- [ ] **T8.2** Internal dashboard: query volume by intent class, refusal rate over time, concession rate over time, cost per day.
- [ ] **T8.3** `EVALS.md` — public results table, version by version, plus failure taxonomy. In-corpus recall / out-of-corpus refusal rate reported as a pair throughout.
- [ ] **T8.4** `SECURITY.md` — red team results per rule, before and after.
- [ ] **T8.5** README — the six architecture decisions from `docs/ARCHITECTURE.md`, each with the rejected alternative and what it cost. Include the corpus-simplification story (why NCAP/warranty were dropped, and what that shifted the hard problem to) and the EX30-no-competitor decision — both are genuine engineering judgment calls, not just scope cuts.
- [ ] **T8.6** 90-second demo: a normal comparison, a concession response (service network or EX30), and a clean refusal on an out-of-corpus question (e.g. "what's the safety rating?"). The refusal demo is as important as the other two — it's the hardest thing this version of the system does.

---

## Working notes

- Read `AGENTS.md` and `docs/CORPUS.md` before every session
- If a document isn't in `CORPUS.md`, it isn't in scope — don't ingest it, don't chase it
- One task per session; report eval deltas, especially the in-corpus recall / out-of-corpus refusal rate pair
- If a task reveals the plan is wrong, update this file before continuing
