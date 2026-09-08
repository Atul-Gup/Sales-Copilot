# PRD — Showroom Copilot

*Sales consultant assistant for Volvo Cars India dealerships.*

Status: v2 · Portfolio project, unaffiliated with Volvo Cars
Supersedes v1 (structured spec database + separate NCAP/warranty corpus + three-screen UI).

---

## 1. Problem

A Volvo sales consultant is standing beside an XC60 with a customer who has spent three months researching. The customer says: *"The X3 holds its value better and BMW has a service centre in my city. Why would I buy this?"*

The consultant has about ten seconds. They answer from memory, and one of three things goes wrong: they overstate a claim that doesn't hold up, they understate a real Volvo advantage, or they deflect and lose the room.

## 2. Who it's for

The Volvo Cars India sales consultant, on the showroom floor, on their phone, mid-conversation. Not customer-facing.

## 3. Why this is hard in a way that matters

Volvo genuinely loses some of these comparisons — service network reach and resale value are real weaknesses against BMW and Mercedes in India. A tool that spins them gets caught and abandoned after two uses. **The differentiator is honesty under pressure**: when the customer's objection is factually correct, the system concedes it and gives the consultant something honest to say next. This is measured, not aspirational — see §6.

## 4. Product shape: closed-book chat over a curated document set

**One unified chat interface.** The consultant types a question — spec, comparison, or objection, doesn't matter which — and gets one natural-language answer. There is no separate comparison screen or objection screen; internally the system still classifies intent to choose how to respond, but the consultant never sees that routing.

**The system answers only from documents it has been given**, and says so plainly when it doesn't have something. This is the core discipline: it must never fall back on what the underlying model already knows about Volvo, BMW, or car safety in general. A wrong number is bad. A confidently wrong answer sourced from nowhere is worse, because nothing catches it.

## 5. Scope

### Corpus — what the system can answer from

One reformatted product document per model, competitors included:

| Volvo model | Competitor documents |
|---|---|
| XC60 | BMW X3, Mercedes GLC, Audi Q5 |
| EX30 | *(none — see note)* |

**EX30 has no ingested competitor.** No usable BMW iX1 document was sourced (the only file obtained was a mislabelled BMW X1, a petrol car, and was rejected rather than used). The correct, honest answer to "what competes with the EX30?" is that no German rival exists in its price class — and that answer is itself a useful, true thing to tell a customer. This is documented as a deliberate scope decision in `docs/CORPUS.md`, not a gap to quietly work around.

**Service centre locations** are a second, separate data source — a structured spreadsheet, not a chunked document — checked by direct city lookup. It remains in scope; it was not affected by the corpus simplification below.

### Explicitly out of scope for this version

| Excluded | Why |
|---|---|
| Euro NCAP safety ratings | Descoped to simplify the corpus to one document type. The system must refuse safety-rating questions rather than answer from general knowledge |
| Warranty / service-plan terms (any brand) | Same reasoning. India service-plan documentation was never available in any case |
| Equipped-price comparison (originally scoped as T2.4) | None of the five product documents contain pricing or an itemized standard-vs-optional equipment breakdown — each brochure explicitly disclaims exact tier/price detail. Building this would mean fabricating figures the sources never state, which the closed-book discipline in §4 forbids. The system refuses price and equipment-tier questions via `no_answer_outside_corpus` instead |
| Customer-facing chat | Different risk profile — this is an internal tool |
| Live dealer inventory, CRM, finance/EMI, used cars, voice input | Deferred — not needed to demonstrate the core behaviors |

If NCAP or warranty data proves genuinely necessary (e.g. consultant interviews show it's a constant question), it can be added back as its own document category later. Until then it is a named absence, handled by refusal, not a silent hole.

## 6. Success metrics

| Metric | Target | Why |
|---|---|---|
| **Hallucinated-fact rate** | < 1% | A fabricated claim in front of a customer is the worst failure mode |
| **In-corpus recall** | > 90% | Does it answer when the documents genuinely support an answer |
| **Out-of-corpus refusal rate** | > 95% | Does it correctly decline when nothing supports an answer — reported as a pair with recall, never alone |
| **Citation validity** | > 98% | Does the cited passage actually contain the claim |
| **Honest-concession rate** | > 90% | On objections where the customer is factually right, does it concede rather than deflect. No comparable product measures this |
| **Refusal accuracy (red team)** | 100% | On the adversarial guardrail set |
| **Over-refusal rate** | < 5% | Reported beside refusal accuracy always — a tool too cautious to answer "which has more boot space" is useless |
| p95 latency | < 2s | Every query goes through retrieval and full LLM generation now (no template path) — hit via caching and streaming, not a shortcut around generation |
| Cost per query | < ₹2 | Dealership economics |

**In-corpus recall / out-of-corpus refusal rate is the new headline pair**, alongside honest-concession rate. Together they measure the two things this version of the product is actually built to prove: it stays inside its evidence, and it tells the truth when the evidence is unflattering.

## 7. Non-goals

Not trying to make Volvo win every comparison. Not a replacement for product training. Not autonomous. Not comprehensive across every market, model year, or safety/warranty question — it is honest about what it doesn't cover, which is the point.

## 8. Risks

| Risk | Mitigation |
|---|---|
| Model answers from general knowledge instead of the documents | `no_answer_outside_corpus` guardrail, tested against `out_of_corpus.jsonl` |
| Retrieval returns *something* even when nothing is relevant | Calibrated `in_corpus?` threshold, not a default similarity cutoff — see `RETRIEVAL.md` |
| EX30 has no competitor — feels like a gap | Documented, and turned into the concession behavior ("no direct German rival") rather than hidden |
| Consultant over-trusts fluent chat prose | Citations and "don't claim" content must stay visually distinct inside the chat response, not dissolve into generic prose |
| No Volvo dealer near the builder for validation | Interview German-luxury consultants locally, or phone a Volvo dealer in Pune/Ahmedabad |

## 9. Validation

Before finishing the objection layer, talk to at least one working luxury-segment sales consultant about what they actually get stuck on. The current objection set is an assumption and is likely wrong about which objections matter most.

## 10. Open questions

1. Is warranty/safety data worth adding back once real usage shows it's a constant question?
2. Should the EX30's "no competitor" framing extend to other price-asymmetric situations if the lineup grows?
3. Does the calibrated `in_corpus?` threshold hold up once the corpus grows past five documents, or does it need recalibrating per-document?
