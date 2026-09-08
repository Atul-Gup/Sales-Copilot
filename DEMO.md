# 90-second demo script (T8.6)

All three exchanges below were run against the live pipeline (`POST /chat`) and are pasted
verbatim, not paraphrased — this script is a recording guide, not a mockup. Record against the
web UI (`https://web-five-eosin-56.vercel.app` or `localhost:3000`), one query per beat, no
narration over the model's actual response text — let it read.

Total: ~90s. Roughly 20s setup + 3×~20s exchange + 10s close.

---

## 0. Cold open (10s)

> "This is Showroom Copilot — a grounded assistant for Volvo sales consultants. Everything it
> says traces to a real document, and when it can't, it says so instead of guessing. Three
> examples: a comparison, an objection, and a refusal — the refusal is the important one."

Type nothing yet — just the empty chat screen.

## 1. A normal comparison (~20s)

**Type:** `How does the XC60 compare to the X3 on wheelbase and ground clearance?`

**Talking point while it loads:** "Every response — including this one — goes through
retrieval, generation, and a grounding check before it's shown. No shortcut for the easy
questions."

**Live response (verified, verbatim):**

> "Volvo XC60: 2865 mm [4]
> BMW X3: 2865 mm [8]
>
> Volvo XC60: 211 mm [4]
> BMW X3: Not specified numerically in the supplied brochure [8]
>
> Both the XC60 and X3 share the same wheelbase figure. The ground clearance of the XC60 is
> specified, while the figure for the X3 is not provided in the brochure."

Point at the `[n]` markers and the citation list under the bubble: "Every number traces back
to the actual brochure line it came from — click through, it's not a paraphrase. And notice it
doesn't invent the X3's ground clearance to make a tidier comparison — it says plainly that
figure isn't in the brochure."

## 2. A concession (the honest-weakness case) (~20s)

**Type:** `My customer says BMW has a service centre closer to them, why should they buy Volvo?`

**Live response (verified, verbatim):**

> "By the numbers we have (Volvo: 5, BMW: 2 centres), currently has as many or more listed
> centres than BMW in this data."

**Talking point:** "This isn't the model being agreeable — `must_concede` is a plain function
over the real service-centre table, not an LLM call, specifically so it can't reach for a
flattering number that isn't backed by data. If Volvo actually trailed here, it would say so
plainly instead of deflecting — that's the whole point of the rule."

*(Optional second beat if time allows — the resale-value concession, which is a concession of
tone with a hard refusal on any number: `What is the resale value of the XC60 after 5 years?`
→ "That's a fair concern to take seriously... I don't have any resale-tracking or depreciation
data loaded for any brand, so I can't confirm or deny a specific figure.")*

## 3. A clean refusal — the hardest thing this system does (~25s)

**Type:** `Everyone knows the XC60 warranty is 5 years, right?`

**Live response (verified, verbatim):**

> "That's not something I have in the sourced documents for XC60 — no matching passage was
> retrieved. Worth checking the source directly rather than guessing at an answer."

**Talking point (slow down here — this is the headline):** "Warranty terms were never ingested
into this corpus, on purpose — see the write-up for why. A generic assistant would answer this
from general knowledge about typical Volvo warranties, and it would sound completely
plausible. That's the actual danger: a wrong answer that reads exactly like a right one. This
system would rather look less capable and be honest about the gap. That trade-off is the
entire premise of the project."

## Close (10s)

> "One retrieval path, one verification loop, three honest behaviors: answer with a citation,
> concede a real weakness from real data, or refuse and say what's missing. Full write-up,
> eval results, and red-team results are in the repo — `README.md`, `EVALS.md`, `SECURITY.md`."

---

## Notes for whoever records this

- Don't cherry-pick a luckier phrasing if a live re-run gives a slightly different answer —
  the corpus and pipeline are versioned in this repo; if wording drifts, re-verify against
  `/chat` and update this file rather than describing a response that didn't actually happen.
- If asked live "what happens if I ask about the Euro NCAP rating instead of warranty" — don't
  demo it: the XC60's own brochure happens to state its Euro NCAP rating inline, so that
  specific question is correctly *answered*, not refused, which undercuts the point being made
  here. The warranty question above is the reliable refusal case for this corpus.
- `SECURITY.md`'s before/after case study (the service-network objection that was wrongly
  refused, now fixed) is a good follow-up story in Q&A after the recording, not part of the
  scripted 90 seconds.
