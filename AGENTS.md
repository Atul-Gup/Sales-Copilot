# AGENTS.md — Showroom Copilot

Rules loaded before every agent task. Keep this file under 12,000 characters.

## What this project is

An AI assistant for **Volvo Cars India dealership sales consultants**. A consultant standing with a customer asks it for a competitive comparison or help with an objection, and gets a cited, defensible answer in under two seconds.

It competes against BMW, Mercedes-Benz, and Audi in the Indian luxury segment.

**This is an unaffiliated portfolio project built on public information.** Never use Volvo trademarks or logos in the UI. Never imply endorsement or partnership.

## Read these before non-trivial work

- `docs/PRD.md` — product definition, scope, success metrics
- `docs/ARCHITECTURE.md` — stack, data model, eval metric definitions
- `docs/GUARDRAILS.md` — the rules the system must never break
- `docs/TASKS.md` — sequenced backlog; work one task at a time

## Non-negotiable rules

### 1. Citation is a schema constraint, not a prompt instruction

Every fact row in the database carries a `source_id` referencing the `sources` table. The retrieval API **must not** be able to return a fact without one. Do not add a code path that lets an uncited fact reach the model.

If you find yourself writing "please cite your sources" in a prompt as the primary enforcement mechanism, stop — the constraint belongs in the data layer.

### 2. Spec lookups never touch an LLM

Structured questions ("boot space of the XC60", "which variants have a panoramic roof under ₹70 lakh") resolve as SQL against typed columns. LLM generation is only for objection handling and comparison narrative.

This is the latency budget. Do not route spec queries through the model for convenience.

### 3. Primary sources only

Permitted: Volvo Cars India official site, BMW/Mercedes-Benz/Audi India official sites, Euro NCAP, official homologated range and efficiency figures, Volvo's own dealer and service locator.

Forbidden: CarWale, CarDekho, ZigWheels, CarTrade, and every other aggregator. They disagree with each other and a consultant quoting them has no defence.

### 4. Never compare across safety protocols

Euro NCAP and Bharat NCAP use different protocols and are not on the same scale. Volvo India is not BNCAP tested. Any request to compare a Euro NCAP score against a BNCAP score must be refused with an explanation, not answered.

### 5. When the customer is right, concede

Volvo genuinely loses on service network reach, resale value, and brand prestige in India. The system must acknowledge valid criticism and give the consultant something honest to say next. Never spin, never deflect, never overstate service coverage.

A tool that claims Volvo wins everything gets caught in two uses and is then never trusted again.

### 6. Never state as fact

- On-road price (varies by city registration — quote ex-showroom and say so)
- Delivery timelines
- Discounts or finance approval
- Service availability in a city without checking the locator data

## Stack

- **Backend:** Python 3.12, FastAPI, SQLAlchemy, Pydantic v2
- **Database:** PostgreSQL 16 with pgvector. One database — do not add a separate vector store
- **Frontend:** Next.js (App Router), TypeScript, Tailwind. Mobile-first; consultants use phones
- **LLM:** provider-agnostic behind `llm/client.py`. Never import a vendor SDK outside that module
- **Evals:** pytest, results committed as JSON under `evals/results/`

Do not add dependencies without a note in the PR description explaining why an existing one won't do.

## Conventions

- Type hints on every Python function. Pydantic models for all API boundaries
- No bare `except:`. Every external call has explicit error handling and a timeout
- Prices stored as integer paise, never floats
- All timestamps UTC in the database, formatted at the edge
- Structured logging via `structlog`. Every LLM call logs model, tokens, latency, and cost
- Tests alongside code as `test_*.py`. New logic ships with a test

## What "done" means

A task is not done until:

1. It runs — you executed it, not just wrote it
2. Tests pass, including the eval suite if you touched the pipeline
3. New behaviour has a test
4. If you changed the pipeline, you ran `evals/run_eval.py` and the metrics did not regress

**Report eval deltas in your summary.** "Hallucinated-spec rate 2.1% → 0.9%" is the useful output. "Improved accuracy" is not.

## What to do when stuck

- **Missing spec data?** Do not invent a plausible figure. Insert a row with `verified = false` and flag it. A wrong spec in front of a customer is the worst failure this system has.
- **Unclear requirement?** Check `docs/PRD.md`, then ask. Do not guess at product decisions.
- **Guardrail seems to block something legitimate?** Say so rather than weakening it. Over-refusal is a tracked metric — flag it and let it be a deliberate decision.

## Anti-patterns

- Adding a chat interface as the primary UI. This is a fast-lookup tool; chat is a fallback
- Adding a vector store when Postgres and pgvector already cover it
- Broadening scope beyond Volvo India's current lineup and the three German competitors
- Building the objection layer before the eval set exists
- Marking work complete without running it
