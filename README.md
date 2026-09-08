# Showroom Copilot

A grounded-answer assistant for Volvo Cars India sales consultants — standing on the showroom
floor, phone in hand, mid-conversation with a customer who's spent three months researching.
It answers spec questions, comparisons, and objections from a small corpus of real product
documents, and it is built to **refuse plainly rather than guess** whenever the corpus doesn't
support an answer. Portfolio project, unaffiliated with Volvo Cars.

Live: `https://showroom-copilot-api-production.up.railway.app` (API) ·
`https://web-five-eosin-56.vercel.app` (web)

See `EVALS.md` for results and `SECURITY.md` for red-team results, both versioned and both
reporting known gaps, not just wins.

## The central idea

**The system may only state what a retrieved document supports, and must say so plainly when
nothing does.** There is no structured fact database — no `specs`/`safety_ratings` table to
short-circuit retrieval. Every answer, including a simple spec lookup, goes through the same
retrieve → generate → verify path; what varies is which prompt style a question gets, not
whether retrieval and verification happen.

```
                    ┌── classify (SPEC | COMPARISON | OBJECTION)
                    │    picks the prompt, never skips retrieval
   query ───────────┤
                    └─ must_concede? (known-weakness objections, from real data)
                           │no
                           ▼
                    retrieve (hybrid: dense + BM25 + RRF)
                           │
                    in_corpus? (calibrated threshold)
                       │no                    │yes
                       ▼                       ▼
                  refuse_gracefully       generate → verify_grounding
                  (name what's missing)   (regenerate once → accept | refuse)
```

## Six decisions, and what each one cost

### 1. One document corpus, not structured fact tables + a separate narrative corpus

An earlier draft kept `specs`/`features`/`safety_ratings` tables alongside a chunked corpus, so
a spec lookup could skip retrieval entirely. Dropped: the source documents were already
well-formatted tables, so a second structured layer added a second thing that could drift out
of sync with the documents themselves, without adding accuracy — every fact still has to trace
to a document either way. **Cost:** a plain spec lookup ("what's the XC60's wheelbase?") is now
exactly as retrieval-dependent as an open comparison, so it can be wrong in the same ways a
comparison can — there's no faster, more-trusted path for the easy questions.

### 2. Closed-book refusal over broader, less-verified coverage

Euro NCAP ratings, Volvo's warranty terms, and service-plan coverage were all sourced early in
this project and then dropped from the corpus (`docs/CORPUS.md`) — not because they don't
matter to a real customer conversation, but because a smaller corpus the system stays honest
about beats a broader one it might silently supplement from the underlying model's general
training knowledge. **Cost:** the system refuses real, common questions ("what's the safety
rating?") that a consultant will actually be asked — the refusal has to be good enough (name
what's missing, suggest where to check) that this doesn't read as the system being unhelpful.

### 3. A calibrated `in_corpus?` threshold, not a default similarity cutoff

The retrieval gate's fused RRF score doesn't separate in-corpus from out-of-corpus questions
cleanly on its own (T3.6's calibration finding, `docs/RETRIEVAL.md`) — a library-default cutoff
would have meant guessing. The threshold (`0.031778`) was calibrated against labelled
in-corpus/out-of-corpus question sets instead. **Cost:** even calibrated, the gate can still be
beaten by lexical overlap alone — a question naming an in-scope model about a genuinely
out-of-corpus topic (Euro NCAP) can still score above threshold (see `SECURITY.md`'s `rt_041`).
A second, explicit override (`_is_framing_pressure_for_uncorpused_topic`) exists specifically
because the calibrated score alone wasn't enough for that one class of question.

### 4. Full LLM generation for every response, not a templated SPEC path

An earlier draft templated SPEC answers directly from a retrieved value, which protects numeric
fidelity by construction — no generation step means no chance to paraphrase a number wrong. Reversed:
templating produced an inconsistent voice across a single unified chat interface (a templated
spec answer reads nothing like a generated comparison), which defeats the point of having one
interface at all. **Cost, stated honestly:** the numeric-fidelity protection moved downstream
into `verify_grounding` — every stated number is checked against its source chunk, with a
regenerate-once-then-refuse loop on a mismatch — which trades a generation-time guarantee for a
verification-time check, and means every query, including the simplest lookup, now makes a full
LLM call. This is also why `model_labels` had to be added later (see `EVALS.md`'s failure
taxonomy): a chunk carrying no model name of its own is a real way for generation to attribute
one model's figure to a different model, in a way a template could never have allowed.

### 5. One unified chat interface, not separate comparison/objection/spec screens

Every intent goes through the same `POST /chat` endpoint and the same chat surface — no
`/compare` or `/objection` route, no separate UI screen per intent class. **Cost:** refusals and
concessions have to stay visually legible *inside* a normal-looking chat bubble rather than
living on a dedicated screen that signals "this is different" by its layout alone; the current
UI addresses this with distinct callout styling (an amber "not in the sourced documents" box
for refusals, a labeled concession box), but making a citation marker itself visually distinct
from prose (rather than a plain list under the answer) is still an open task (`docs/TASKS.md`
T7.2).

### 6. The EX30 ships with zero competitors, not a mismatched one

The nearest German rival to the EX30 by price is the BMW iX1 — but no correct iX1 document was
ever sourced. The only BMW file obtained was a mislabelled X1: a different class, a different
powertrain (petrol ICE, not electric), and using it as a stand-in would have meant comparing
the EX30 against a vehicle it doesn't actually compete with. **Cost:** the system can't answer
"how does the EX30 compare to the iX1?" at all — it concedes the gap explicitly
(`concede.py::EX30_PRICE_CLASS_GAP_CONCESSION`) rather than filling it. This was a deliberate
data-honesty call, not an oversight: "the EX30 has no direct German rival at its price" is a
true and useful thing to tell a customer, and a stronger answer than forcing a mismatched
comparison to fill the slot.

## Architecture, in brief

- **Retrieval** (`api/services/retrieve.py`) — hybrid dense (cosine similarity) + BM25, fused by
  reciprocal rank fusion. No reranker (dropped, see `docs/RETRIEVAL.md`).
- **Generation** (`api/services/generate.py`) — one LLM call per query, every intent class,
  guided by intent-specific prompt rules, not separate code paths.
- **Verification** (`api/services/verify.py`) — a LangGraph `generate → verify → accept |
  regenerate once | refuse` cycle checking both numeric grounding and output guardrails
  together.
- **Concession** (`api/services/concede.py`) — deterministic, non-LLM handling of three
  documented known-weakness objection categories (service network, resale value, EX30's
  missing competitor), checked on every query before retrieval, never gated behind intent
  classification (a real bug found and fixed — see `SECURITY.md`'s before/after case study).
- **Guardrails** (`api/guardrails/`) — rules as data (`rules.py`), input checks (prompt
  injection, out-of-scope, customer-facing drafting) that run before classification, output
  checks that run inside the verify_grounding loop.
- **Observability** (`api/logging.py`, `api/models/event.py`) — structured JSON logs on every
  retrieval/embedding/generation call, plus a persisted `query_events` table backing a small
  token-gated internal dashboard (`GET /admin/dashboard`) for query volume, refusal/concession
  rate, and cost per day.

## Repo layout

```
api/
├── routers/     chat (single endpoint), admin (ingest + metrics), health
├── services/    router (intent), retrieve, generate, verify, concede, pipeline
├── guardrails/  input.py, output.py, rules.py
├── llm/         client.py (the only vendor SDK import), embeddings.py
└── models/      chunk, catalog, network, source, event
ingest/          parse/chunk/embed the product-doc corpus, service-centre spreadsheet
evals/           dataset/, metrics.py, run_*.py, results/ (committed)
web/             Next.js chat interface
docs/            PRD, ARCHITECTURE, GUARDRAILS, CORPUS, RETRIEVAL, TASKS
```

## Running locally

```
# .env: DATABASE_URL=sqlite:///./dev.db, ADMIN_INGEST_TOKEN=<any value>
python -m uvicorn api.main:app --reload
curl -X POST localhost:8000/admin/ingest -H "x-admin-token: <token>"   # once

cd web && npm run dev
```

`python -m pytest`, `ruff check .`, `python -m mypy api/` before any deploy.
