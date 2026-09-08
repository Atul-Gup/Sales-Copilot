# AGENTS.md — Showroom Copilot

Rules loaded before every agent task. Keep this file under 12,000 characters.

## What this project is

An AI assistant for **Volvo Cars India dealership sales consultants**. A consultant standing with a customer asks a single unified chat interface for a competitive comparison or help with an objection, and gets a natural-language answer grounded only in a small set of curated product documents — with citations and any "what not to claim" content staying visible inside that answer.

**This is an unaffiliated portfolio project built on public information.** Never use Volvo trademarks or logos in the UI. Never imply endorsement or partnership.

## Read these before non-trivial work

- `docs/PRD.md` — product definition, scope, success metrics
- `docs/ARCHITECTURE.md` — stack, data model, eval metric definitions
- `docs/CORPUS.md` — the authoritative, exhaustive source list. If a document isn't listed there, it is not in scope
- `docs/RETRIEVAL.md` — retrieval and generation design, the `in_corpus?` gate, refusal behaviour
- `docs/GUARDRAILS.md` — the rules the system must never break
- `docs/TASKS.md` — sequenced backlog; work one task at a time

## Non-negotiable rules

### 1. Citation is a schema constraint, not a prompt instruction

Every chunk carries a `source_id` referencing the `sources` table. Retrieval **must not** be able to return a chunk without one, and generation must not state a claim with no corresponding retrieved chunk. If you find yourself relying on "please cite your sources" in a prompt as the primary enforcement mechanism, stop — the constraint belongs in the data layer and in `verify_grounding`, not in prose.

### 2. The system answers only from the documents in CORPUS.md — and says so when it can't

There is no structured fact database. The corpus is five reformatted product documents (`docs/CORPUS.md`). Every query goes through retrieval; a calibrated `in_corpus?` threshold decides whether to generate an answer or refuse. **When there's no supporting document — safety ratings, warranty, service-plan terms — refuse and name what's missing. Never let the underlying model answer from its own general knowledge.** This is the single most important rule in this codebase. Full design in `docs/RETRIEVAL.md`.

### 3. Every response is generated, and every number is verified afterward

There is no template path anymore — all intent classes (SPEC, COMPARISON, OBJECTION) generate a natural-language response through the LLM, over the retrieved chunks. This is deliberate: a mix of templated and generated replies reads as inconsistent inside a single chat surface.

Because generation is free-form, `verify_grounding` must check **every number and unit stated in the response against its retrieved source value**, exact match or an explicitly stated tolerance — not just check that a claim has *some* supporting chunk. A numeric mismatch (e.g. 483L restated as "around 480L") is a grounding violation with the same regenerate-once-then-refuse handling as an uncited claim. Report **numeric fidelity rate** as its own metric, separate from hallucinated-fact rate — see `docs/RETRIEVAL.md`.

### 4. Primary sources only, and only what's in CORPUS.md

Every document in the corpus is listed by name in `docs/CORPUS.md`. Do not source, ingest, or reference anything not on that list — including anything from aggregators (CarWale, CarDekho, ZigWheels, etc.), which is never permitted regardless of corpus scope.

### 5. When the customer is right, concede

Volvo genuinely loses on service network reach and resale positioning in India, and the EX30 has no direct German rival at its price. The system must acknowledge this and give the consultant something honest to say next — never spin, never deflect. See `must_concede` in `docs/GUARDRAILS.md`.

### 6. Never state as fact

On-road price (varies by city — quote ex-showroom and say so), delivery timelines, discounts or finance approval, service availability not confirmed in the service-centre data.

## Stack

- **Backend:** Python 3.12, FastAPI, SQLAlchemy, Pydantic v2
- **Database:** PostgreSQL 16 with pgvector. One database
- **Frontend:** Next.js (App Router), TypeScript, Tailwind. Mobile-first; consultants use phones. **Single unified chat interface** — one input, one natural-language response stream. Not separate screens per query type
- **LLM:** provider-agnostic behind `llm/client.py`. Never import a vendor SDK outside that module
- **Embeddings:** OpenAI `text-embedding-3-small`, cached, behind `llm/embeddings.py`
- **Orchestration:** LangGraph, scoped to the retrieve→generate→verify→(regenerate|refuse) cycle — it has a genuine loop. Nothing else needs a graph framework
- **Evals:** pytest, results committed as JSON under `evals/results/`

## Conventions

- Type hints on every Python function. Pydantic models for all API boundaries
- No bare `except:`. Every external call has explicit error handling and a timeout
- Prices stored as integer paise, never floats. Price fields are nullable — do not insert a placeholder or estimated price where no source exists
- Structured logging via `structlog`. Every LLM and embedding call logs model, tokens, latency, and cost
- Tests alongside code as `test_*.py`. New logic ships with a test

## What "done" means

1. It runs — you executed it, not just wrote it
2. Tests pass, including the eval suite if you touched the pipeline
3. New behaviour has a test
4. If you touched retrieval or generation, you ran `evals/run_eval.py` and report the metric deltas in your summary — especially in-corpus recall vs out-of-corpus refusal rate, always as a pair

## What to do when stuck

- **A document isn't in `docs/CORPUS.md`?** Don't ingest it. Flag it and stop.
- **Missing or ambiguous data in a document you're allowed to use?** Don't infer or fill from a related model. Flag it with `verified=false` and the source location.
- **Unclear requirement?** Check `docs/PRD.md`, then ask.
- **A guardrail seems to block something legitimate?** Say so rather than weakening it silently. Over-refusal is a tracked metric — flag it and let it be a deliberate, measured decision.

## Anti-patterns

- Recreating structured fact tables (`specs`, `features`, `safety_ratings`) — the corpus is documents now; if this seems necessary, the scope has drifted and `docs/CORPUS.md` needs updating first, not the schema
- Ingesting anything not named in `docs/CORPUS.md`, including NCAP, warranty, or aggregator data
- Letting the model answer an out-of-corpus question from general knowledge instead of refusing
- Letting citations or "don't claim"/concession content dissolve into generic conversational prose in the chat UI
- Substituting a mismatched document (e.g. the BMW X1) for a missing one (the iX1) rather than leaving the gap honest
- Marking work complete without running it
