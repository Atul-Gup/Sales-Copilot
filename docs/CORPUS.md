# CORPUS — Showroom Copilot

The authoritative list of what data exists and how to treat it. Ingestion and retrieval build against this file. If a document isn't listed here, it isn't in scope — do not go hunting for it, and do not ingest anything not named below.

---

## Model scope

| Volvo model | Competitor documents |
|---|---|
| **XC60** | BMW X3, Mercedes GLC, Audi Q5 |
| **EX30** | *(none)* |

**EX30 has no ingested competitor, by design.** The nearest German rival by price is the BMW iX1, roughly 20% more expensive — but no usable iX1 document was ever sourced. The only BMW file obtained was a mislabelled X1 (petrol ICE, a different class and powertrain entirely) and was rejected rather than used or substituted.

This is a deliberate, documented gap: **"the EX30 has no direct German rival at its price" is a true and useful thing to tell a customer**, and it's a stronger answer than forcing a mismatched comparison to fill the slot. If a correct iX1 document is sourced later, add it here and to `data/sources/products/bmw/`.

---

## The corpus — the entire set of documents the system can answer from

| Document | Format | Location |
|---|---|---|
| Volvo XC60 product document | Word/PDF, reformatted | `data/sources/products/volvo/xc60` |
| Volvo EX30 product document | Word/PDF, reformatted | `data/sources/products/volvo/ex30` |
| BMW X3 product document | Word/PDF, reformatted | `data/sources/products/bmw/x3` |
| Mercedes GLC product document | Word/PDF, reformatted | `data/sources/products/mercedes/glc` |
| Audi Q5 product document | Word/PDF, reformatted | `data/sources/products/audi/q5` |
| Volvo Objection Handling Guide | Word/PDF, **pre-chunked** — 28 numbered items, chunk IDs `EX30_001`–`GENERAL_029` (item 9 removed — it conflicted with the EX30 no-competitor scope decision above) | `data/sources/products/volvo/objection-handling` |

Each document is self-contained: one model, dimensions, powertrain, and feature descriptions, in one file. Chunked and embedded per `docs/RETRIEVAL.md`. Every chunk carries `source_id NOT NULL`, enforced at the schema level — collapsing to one corpus type did not relax the citation discipline.

**The objection handling guide is a different shape and must be ingested differently:**
- It is **already chunked** — 28 numbered objection/response units. Do not run the semantic chunker on it. Split on the existing numbered boundaries exactly, one chunk per item, and store the given ID (`EX30_001`, `XC60_010`, `GENERAL_027`, etc.) as `chunks.external_id`.
- It is **cross-referential** — items compare XC60 against X3, GLC, and Q5. It does not belong to a single brand folder the way the five per-model product documents do.
- It gets **its own `sources` row** (`source_id = src_volvo_objection_guide`). Each item's internal "Supporting source" text (e.g. "EX30 brochure: Powertrain & Performance") is descriptive content inside the chunk, not a separate citation target — it does not point to a different `source_id` unless that underlying brochure is also independently ingested.
- Items 13, 20, 21, 22, 23, 27, 29 are hand-written examples of correct refusal/concession behaviour. Promote them directly into `evals/dataset/concessions.jsonl` and `qa.jsonl` as ground truth, not just as retrieval content.

**No document contains pricing or an itemized standard-vs-optional equipment breakdown.** Each brochure explicitly disclaims this ("exact standard/optional availability should be read [elsewhere]", "some equipment described/shown may only be available at extra cost" — no itemization). Equipped-price comparison (originally scoped as T2.4) was descoped for this reason: `no_answer_outside_corpus` refuses price and equipment-tier questions rather than the system fabricating figures the source documents never state. See `docs/PRD.md` §5 for this as a named scope decision.

**Service centre locations are a second, separate, retained source** — a structured spreadsheet (T1.7), checked by direct city lookup rather than retrieval. It was not affected by the corpus simplification and remains in scope. "Answer only from available documents" means available *data*, not literally the Word/PDF set — the `service_overstatement` guardrail still checks against it.

---

## Explicitly excluded — do not ingest, do not source

| Excluded | Why | What the system does instead |
|---|---|---|
| Euro NCAP reports, all models | Descoped to simplify the corpus to one document type | Refuse via `no_answer_outside_corpus` |
| Volvo warranty (India) | Same reasoning | Refuse |
| Volvo service plan | Was never available for India in the first place | Refuse |
| Any competitor warranty/service document | Never in scope | Refuse |
| BMW iX1 (the correct document) | Not yet sourced — the file obtained was actually the X1 | EX30 stays without a competitor until this is fixed; do not substitute the X1 |
| Any aggregator (CarWale, CarDekho, ZigWheels, etc.) | Disagree with each other and with manufacturer sources | Never used, at any point in this project |

This is not permanent. If NCAP or warranty data turns out to matter — e.g. consultant interviews show it's a constant question — add the documents and extend `no_answer_outside_corpus`'s scope accordingly. Until then, the system must refuse rather than answer from the model's general knowledge about Volvo's safety reputation, typical warranty terms, or anything else it wasn't given a document for.

---

## Data provenance summary

| Document | Market | Status |
|---|---|---|
| XC60 product doc | India | ✅ in scope |
| EX30 product doc | India | ✅ in scope |
| X3 product doc | India | ✅ in scope |
| GLC product doc | India | ✅ in scope |
| Q5 product doc | India | ✅ in scope |
| Objection handling guide (28 items) | India | ✅ in scope — pre-chunked, own source row, item 9 removed |
| Service centre spreadsheet | India | ✅ in scope, separate structured source |
| iX1 product doc | — | ❌ not sourced — EX30 has no competitor until fixed |
| Euro NCAP, any model | — | ❌ descoped — refuse, don't answer from general knowledge |
| Warranty / service plan, any brand | — | ❌ descoped — refuse, don't answer from general knowledge |

Every fact the system states traces to a ✅ row. Everything else triggers `no_answer_outside_corpus`.
