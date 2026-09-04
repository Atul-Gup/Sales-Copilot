# PRD — Showroom Copilot

*Sales consultant assistant for Volvo Cars India dealerships.*

Status: v1 · Portfolio project, unaffiliated with Volvo Cars

---

## 1. Problem

A Volvo sales consultant is standing beside an XC60 with a customer who has spent three months researching. The customer says: *"The X3 holds its value better and BMW has a service centre in my city. Why would I buy this?"*

The consultant has about ten seconds. They answer from memory, and one of three things goes wrong:

- They overstate — claiming service coverage or resale performance that doesn't hold up, which the customer often already knows is false
- They understate — failing to quantify a real Volvo advantage, like standard-fit equipment against German options-list pricing
- They deflect — which reads as evasion and loses the room

The information that would answer this correctly exists across spec sheets, Euro NCAP reports, dealer locators, and price lists. It is not accessible in ten seconds.

## 2. Who it's for

**Primary user:** a Volvo Cars India sales consultant, on the showroom floor, on their phone, mid-conversation.

**Not built for:** customers. This is an internal tool. Anything customer-facing is a different product with a different risk profile.

## 3. Why this is hard in a way that matters

**Volvo loses some of these comparisons.** Service network reach, resale value, and brand prestige are genuine weaknesses against BMW and Mercedes in India, not perception problems.

Every sales-enablement tool is built to help reps win arguments. That's why consultants stop trusting them — the first time it overstates something the consultant knows is false, the tool is dead.

**So this product's differentiator is honesty under pressure.** When the customer's objection is factually correct, the system says so and gives the consultant an honest next move. This is a measured behaviour, not an aspiration — see §6.

## 4. Scope

### In scope

- Volvo Cars India's current lineup at variant level
- BMW, Mercedes-Benz, Audi India direct competitors for each Volvo model
- Comparison: side-by-side on price, dimensions, powertrain, safety, standard equipment
- Objection handling: fact, framing, and what must *not* be claimed
- Five-year total cost of ownership calculation
- Service network lookup by city
- Battle cards for the main Volvo-versus-German pairs

### Out of scope for v1

| Excluded | Why |
|---|---|
| Customer-facing chat | Different risk profile, different product |
| Live dealer inventory | No DMS access; add via MCP later |
| Lead capture or CRM | Not the problem being solved |
| Finance and EMI calculation | Requires rates we can't verify |
| Used cars | Different data, different objections |
| Voice input | v2 — get the retrieval right first |

## 5. Core flows

### A. Comparison
Consultant selects two vehicles. Gets a side-by-side where differences that matter to this segment surface first, every row carrying its source. Target: under 1 second, because these are precomputed.

### B. Objection
Consultant types or picks an objection. Gets three blocks:

1. **What's true** — with citations
2. **How to frame it** — coaching, not a script to read aloud
3. **What not to claim** — the guardrail made visible

Block 3 is the differentiator. Every competitor tells reps what to say; telling them what they can't substantiate is more useful and protects the dealer.

### C. Spec lookup
Structured question, structured answer, no generation. Under 500ms.

## 6. Success metrics

| Metric | Target | Why |
|---|---|---|
| **Hallucinated-spec rate** | < 1% | A fabricated spec in front of a customer is the worst failure mode |
| **Citation validity** | > 98% | Does the cited source actually contain the claim |
| **Honest-concession rate** | > 90% | On 20 objections where the customer is factually right, does it concede rather than deflect |
| **Refusal accuracy** | 100% | On the 40-prompt red team set |
| **Over-refusal rate** | < 5% | A tool too cautious to answer "which has more boot space" is worthless |
| **p95 latency** | < 2s | The product constraint |
| TCO accuracy | > 95% | Against 30 hand-computed cases |
| Cost per query | < ₹2 | Dealership economics |

**Honest-concession rate is the headline.** No comparable product measures it. It's the metric that encodes the insight in §3.

**Over-refusal is reported alongside refusal accuracy, always.** Guardrails have a cost and hiding it is dishonest.

## 7. Non-goals

- Not trying to make Volvo win every comparison
- Not a replacement for product training
- Not autonomous — it never talks to a customer
- Not comprehensive across every market or model year

## 8. Risks

| Risk | Mitigation |
|---|---|
| Spec data goes stale | `verified_at` on every fact; refuse beyond a staleness threshold |
| Aggregator sources disagree | Primary sources only, enforced at ingestion |
| Consultant over-trusts output | Sources visible on every claim; "what not to claim" always shown |
| Legal exposure from competitor claims | Cite the competitor's own published material; state, never characterise |
| No Volvo dealer near the builder | Interview German-luxury consultants locally; phone Volvo dealers in Pune or Ahmedabad |
| Latency creeps up | Precompute battle cards; spec path never touches the LLM |

## 9. Validation

Before week 7, talk to at least one working luxury-segment sales consultant. Ask what objections they actually get stuck on.

The current objection taxonomy is an assumption. Expect it to be wrong — most likely the real answers are service network, resale, and waiting period rather than specifications. Log what you learn; "informed by interviews with N consultants" is a line very few portfolio projects can write.

## 10. Open questions

1. Does variant-level comparison work when Volvo bundles equipment as standard and the Germans sell it as options? The comparison may need to normalise on equipped price, not list price.
2. How stale is too stale? Prices move; what threshold triggers refusal?
3. Should the consultant be able to override or correct a fact? Useful, but creates an unverified-data path.
4. Is TCO credible without verified resale data, or does it need an explicit assumptions panel?
