# CORPUS — Showroom Copilot

The authoritative list of what data exists, where it came from, and how to treat it. Ingestion (Phase 1) and Corpus B (Phase 4) build against this file. If a document isn't listed here, it isn't in scope — do not go hunting for it.

---

## Model scope: two models

| Volvo model | Why | Competitor set |
|---|---|---|
| **XC60** | Petrol mild-hybrid; India spec + warranty + Euro NCAP all sourced | X3, GLC, Q5 |
| **EX30** | Full India brochure available; carries the EV story | iX1 only (see asymmetry note) |

**EX40 is out of scope** — no India brochure was available. Do not ingest EX40 data.

Two models done properly beats four done on mixed-market data. State the scope decision in the README.

### The EX30 price-class asymmetry (intentional — do not "fix" it)

The EX30 (~₹41 lakh) has **no direct German rival at its price**. The nearest is the BMW iX1 (~₹49 lakh, ~20% more). Mercedes' cheapest EV is the EQA at ~₹66 lakh; Audi's nearest is higher still. These are NOT cross-shopped with the EX30 and must not be ingested as EX30 competitors — pairing a ₹41 lakh car against a ₹66 lakh+ car would put a meaningless comparison into the eval ground truth.

So:
- **EX30's only competitor row is the iX1**, and even that is a price-asymmetric comparison.
- Do NOT source or ingest a Mercedes or Audi EV as an EX30 competitor.
- The asymmetry is a **feature to surface, not a gap to hide.** "The EX30 has no direct German rival — the nearest, the iX1, costs about 20% more" is a true and strong objection-handling answer, and it exercises the concession/contextualise behaviour that is this tool's differentiator.
- Add EX30-vs-iX1 cases to `concessions.jsonl` framed around price positioning, and a spec-eval question whose correct answer names the ~20% price gap.

**Mercedes stays in the corpus, but only as the GLC in the XC60 set** — a petrol ~₹73 lakh rival that genuinely cross-shops with the Q5 and X3. There is no Mercedes entry in the EX30 comparison.

---

## Corpus A — structured facts (the comparison spine)

Ingested as typed rows. Every row carries `source_id`. `source_id NOT NULL` is enforced at the schema level.

### Volvo — India sources (verified)
- **XC60** — India spec sheet. Ex-showroom price, dimensions, powertrain, features by trim.
- **EX30** — India brochure (Volvo Auto India Pvt. Ltd.). Battery 69 kWh, range up to 480 km, 200 kW / 272 hp, 343 Nm, 0–100 in 5.3s, DC 10–80% ~26–28 min, up to 153 kW, boot 318L / 904L folded, frunk 7L, 9-speaker 1040W Harman Kardon, 12.3" display, single variant.

**EX30 caveat:** the brochure disclaimer states some shown configurations may not be offered in India. Any feature not confirmable on the India configurator is ingested with `verified=false` until checked. Do not mark `verified=true` on assumption.

### Competitors — manufacturer India sources (verified)
- **X3, GLC, Q5** — official India spec sheets. XC60's competitor set.
- **iX1** — official India spec sheet. EX30's *only* competitor (see asymmetry note above). No Mercedes or Audi EV in the EX30 set.

Capture the options list with `availability` (`standard` / `optional` / `unavailable`) and `cost_paise` for optional items. This is what powers the equipped-price comparison (T2.4). Without it, that feature can't be built.

### Safety ratings — Euro NCAP (verified, metadata-critical)

All models: XC60, EX30, and the four competitors (X3, GLC, Q5, iX1).

**Every rating row MUST carry:**
- `protocol` = `euro_ncap`
- `year` (publication year)
- `tested_variant` (e.g. "XC60 D4 AWD LHD")
- `status` (`current` / `expired`)
- `adult_score`, `child_score`, `vru_score`, `assist_score` and sub-scores where given

**Known landmine — the XC60 rating:**
- Tested variant: XC60 D4 AWD, **LHD diesel** — not the petrol mild-hybrid Volvo India sells
- Published **2017**, status **EXPIRED** (expired 2024-01-01)
- Scores: adult 98%, child 87%, VRU 76%, safety assist 95%

This must never be presented as a current rating of the car on sale. See the guardrail below.

**Competitor ratings:** capture each with its own year/variant/status. They will differ from the XC60's 2017 protocol. Expired or older competitor ratings are fine — record them honestly. An expired rating handled correctly beats a current-looking fabrication.

---

## Corpus B — narrative documents (document RAG)

Chunked, embedded, sourced. For document-QA queries, not comparison.

### Included (verified India sources)
- **Volvo Warranty (India)** — `volvocars.com/in`. Facts: 2 yr unlimited mileage (ICE), 3 yr / 100,000 km (BEV), accessories match vehicle warranty, corrosion 12 yr.
  - **Discard on ingest:** the "Introducing the Volvo EX90" banner (stray site nav, not warranty content).
  - **Note:** India warranty page does not publish a full exclusions list (the Irish one did). Ingest what exists; don't backfill from other markets.

### Explicitly excluded — do not source
- **Volvo service plan (India)** — not published on the India site. Not available. Record as a scoping limitation in the README. Do NOT substitute the Belgian/EU service-plan document.
- **Competitor warranty documents** — warranty is not a comparison axis in this tool; it's document-QA for the Volvo owner only. Revisit ONLY if consultant interviews show customers actively compare warranties.
- **Competitor service plans** — same reasoning, and no Volvo baseline to compare against anyway.

---

## Guardrail this corpus requires

Add to `docs/GUARDRAILS.md` and `guardrails/rules.py`:

```
Rule(
  id="expired_or_mismatched_rating",
  applies_to=OBJECTION | COMPARISON,
  check: any safety claim must surface protocol, year, and tested_variant,
         and must not present an expired rating as current,
  on_violation=REWRITE,
  message="This Euro NCAP rating is from {year}, tested on {tested_variant},
           status {status}. Present it with that context, not as the current
           rating of the model on sale."
)
```

And extend `cross_protocol_safety`: it already blocks Euro NCAP vs Bharat NCAP. It must ALSO flag when two Euro NCAP ratings from different years/protocols are compared as if equivalent — e.g. the XC60's 2017 rating against a competitor's newer one. Different years, different test regimes, not the same scale.

---

## Data provenance summary

| Document | Market | Status |
|---|---|---|
| XC60 spec | India | ✅ |
| EX30 brochure | India | ✅ |
| X3 / GLC / Q5 spec | India | ✅ (XC60 set) |
| iX1 spec | India | ✅ (EX30 set — sole competitor) |
| Mercedes/Audi EV for EX30 | — | ❌ out of scope — price-class mismatch |
| Euro NCAP — all 6 models | EU protocol | ✅ (metadata-critical) |
| Volvo warranty | India | ✅ |
| Volvo service plan | India | ❌ unavailable — noted limitation |
| Competitor warranty / service | — | ❌ out of scope by design |

Every ingested fact traces to one of the ✅ rows. Nothing else enters the database.
