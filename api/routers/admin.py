"""api/routers/admin.py — POST /admin/ingest (T7.4).

A one-off, idempotent schema-and-corpus provisioning call, not a general
admin surface: creates the `vector` extension and current schema if missing,
then ingests the real product documents, service centres, and the
objection-handling guide — each checked and skipped independently rather
than one blanket "any sources exist" gate, so calling this again after the
five product documents are already loaded still ingests the objection guide
if that hasn't happened yet (real gap found live: the original blanket gate
would have silently skipped the objection guide forever on a database that
already had the five product documents from an earlier deploy). This exists
because the deployed API is the only thing that can reach the database's
internal hostname (Railway's private network) — there is no local/external
path to run migrations or ingestion against it directly.

Also the way to stand up a local dev database: run the API with
`DATABASE_URL=sqlite:///./dev.db` (see `.env.example`) and call this
endpoint once. `CREATE EXTENSION vector` is Postgres-only syntax — skipped
on any other dialect, matching `api/models/vector_type.py::EmbeddingVector`'s
own SQLite fallback, so this endpoint works the same way against either.

Guarded by a shared-secret header rather than left open: this runs real
embedding calls and touches schema, so it must not be callable by anyone
who finds the URL.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import HTMLResponse
from sqlalchemy import text

from api.db import SessionLocal, engine
from api.models import Base, QueryEvent, Source
from api.settings import settings
from ingest.objection_guide import DOCUMENT_TITLE as OBJECTION_GUIDE_TITLE
from ingest.objection_guide import run as ingest_objection_guide
from ingest.product_docs import run as ingest_product_docs
from ingest.service_centres import run as ingest_service_centres

router = APIRouter()


def _check_token(token: str | None) -> None:
    if not settings.admin_ingest_token or token != settings.admin_ingest_token:
        raise HTTPException(status_code=403, detail="forbidden")


@router.post("/admin/ingest")
def admin_ingest(x_admin_token: str | None = Header(default=None)) -> dict[str, Any]:
    _check_token(x_admin_token)

    if engine.dialect.name == "postgresql":
        with engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(engine)

    with SessionLocal() as session:
        existing = session.query(Source).count()
        product_reports: list[Any] = []
        if existing == 0:
            product_reports = ingest_product_docs(session)
            ingest_service_centres(session)
            session.commit()

        objection_guide_status = "skipped"
        objection_guide_result: dict[str, Any] = {}
        has_objection_guide = (
            session.query(Source).filter_by(document_title=OBJECTION_GUIDE_TITLE).first()
            is not None
        )
        if not has_objection_guide:
            report = ingest_objection_guide(session)
            session.commit()
            objection_guide_status = "ok"
            objection_guide_result = {
                "chunk_count": report.chunk_count,
                "malformed_external_ids": report.malformed_external_ids,
            }

    return {
        "status": "ok" if existing == 0 else "product_docs_already_ingested",
        "product_documents": [
            {"document_title": r.document_title, "chunk_count": r.chunk_count, "error": r.error}
            for r in product_reports
        ],
        "objection_guide": {"status": objection_guide_status, **objection_guide_result},
    }


@router.get("/admin/metrics")
def admin_metrics(x_admin_token: str | None = Header(default=None)) -> dict[str, Any]:
    """T8.2: query volume by intent class, refusal/concession rate over
    time, and cost per day — read from `query_events` (`api/models/event.
    py`), the table `api/services/pipeline.py::answer()` writes to on every
    call. Plain SQL aggregation, not a time-series store — this corpus of
    usage data is small enough that a `GROUP BY` on every request is fine,
    and adding one avoids a second thing that can drift out of sync with
    the real data.
    """
    _check_token(x_admin_token)

    # Idempotent, same as /admin/ingest — lets this run against a database
    # /admin/ingest hasn't touched yet (e.g. a fresh local dev.db) without
    # a separate migration step.
    Base.metadata.create_all(engine)

    with SessionLocal() as session:
        events = session.query(QueryEvent).order_by(QueryEvent.created_at).all()

    return _aggregate_metrics(events)


def _aggregate_metrics(events: list[QueryEvent]) -> dict[str, Any]:
    """Pure aggregation over already-fetched rows — small enough data
    (a demo project's query volume) that grouping in Python is simpler and
    more portable across SQLite/Postgres than dialect-specific SQL for a
    boolean sum, and it's independently testable without a database.
    """
    total = len(events)
    refused = sum(1 for e in events if e.refused)
    conceded = sum(1 for e in events if e.conceded)
    grounding_refused = sum(1 for e in events if e.refusal_reason == "grounding_violation")
    # Denominator is "queries that actually reached generation" (i.e. where
    # first_attempt_had_violation isn't null), not every query — a blocked,
    # pre-retrieval-refused, or conceded query never ran generate() at all,
    # so it's neither hallucinated nor not-hallucinated, and folding it into
    # the denominator would understate the rate as usage of those paths grows.
    generated = [e for e in events if e.first_attempt_had_violation is not None]
    first_attempt_violations = sum(1 for e in generated if e.first_attempt_had_violation)

    by_intent: dict[str, int] = {}
    for e in events:
        key = e.intent or "(blocked before classify)"
        by_intent[key] = by_intent.get(key, 0) + 1

    by_day: dict[str, list[QueryEvent]] = {}
    for e in events:
        key = e.created_at.date().isoformat()
        by_day.setdefault(key, []).append(e)

    daily = [
        {
            "date": day,
            "n": len(day_events),
            "refusal_rate": sum(1 for e in day_events if e.refused) / len(day_events),
            "concession_rate": sum(1 for e in day_events if e.conceded) / len(day_events),
            "cost_usd": sum(e.cost_usd or 0.0 for e in day_events),
        }
        for day, day_events in sorted(by_day.items())
    ]

    return {
        "totals": {
            "n": total,
            "refusal_rate": refused / total if total else 0.0,
            "concession_rate": conceded / total if total else 0.0,
            # "how often does the model hallucinate/miscite at all" — over
            # queries that reached generation, regardless of whether a
            # second attempt then fixed it or the query was refused. An
            # accepted response can never itself carry a violation (verify_
            # grounding forces zero before accepting), so this is the only
            # place a real hallucination rate can be measured; see
            # api/models/event.py::first_attempt_had_violation.
            "first_attempt_hallucination_rate": (
                first_attempt_violations / len(generated) if generated else 0.0
            ),
            "generated_n": len(generated),
            # "how often does a hallucination actually reach the user as a
            # refusal" — a strict subset of refusal_rate, broken out by
            # cause rather than lumped in with no_answer_outside_corpus
            # refusals (a different failure mode with a different fix).
            "hallucination_refusal_rate": grounding_refused / total if total else 0.0,
        },
        "by_intent": by_intent,
        "daily": daily,
    }


_DASHBOARD_HTML = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Showroom Copilot — Live Metrics</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet"
  href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap">
<style>
:root{
  --bg:#f4f5f7; --surface:#ffffff; --surface-2:#eceef2; --border:#d7dbe2;
  --text:#1b2027; --text-dim:#5b6472; --text-faint:#8a94a3;
  --accent:#3457a8; --accent-soft:#e4eafc;
  --good:#1f8a5f; --good-soft:#e2f5ec;
  --warn:#a5720b; --warn-soft:#faf0da;
  --bad:#b73c48; --bad-soft:#fbe7e8;
  --shadow: 0 1px 2px rgba(20,24,30,0.04), 0 8px 24px -12px rgba(20,24,30,0.10);
  color-scheme: light dark;
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    --bg:#12151a; --surface:#1a1e25; --surface-2:#20242c; --border:#2c313b;
    --text:#e7eaee; --text-dim:#a3abb7; --text-faint:#707885;
    --accent:#7fa0e8; --accent-soft:#1e2c4a;
    --good:#59c990; --good-soft:#173427;
    --warn:#e0b04d; --warn-soft:#3a2f14;
    --bad:#e8737d; --bad-soft:#3a1e21;
    --shadow: 0 1px 2px rgba(0,0,0,0.3), 0 8px 24px -12px rgba(0,0,0,0.5);
  }
}
* { box-sizing: border-box; }
html, body { background: var(--bg); }
body{
  color:var(--text); font-family:"IBM Plex Sans", system-ui, sans-serif;
  font-size:15px; line-height:1.5; margin:0; padding:2.25rem 1.5rem 4rem;
}
.wrap{ max-width:1080px; margin:0 auto; display:flex; flex-direction:column; gap:2rem; }
.mono{ font-family:"IBM Plex Mono", ui-monospace, monospace; font-variant-numeric: tabular-nums; }

header{ display:flex; flex-direction:column; gap:0.35rem; }
.eyebrow{ font-family:"IBM Plex Mono", monospace; font-size:0.72rem; letter-spacing:0.09em;
  text-transform:uppercase; color:var(--accent); font-weight:600; }
h1{ font-size:1.6rem; font-weight:700; margin:0; text-wrap:balance; letter-spacing:-0.01em; }
.subtitle{ color:var(--text-dim); font-size:0.9rem; max-width:64ch; }

.section-head{ display:flex; align-items:baseline; justify-content:space-between; gap:1rem; margin-bottom:0.8rem; }
.section-head h2{ font-size:1.02rem; font-weight:600; margin:0; }
.section-head .hint{ font-size:0.78rem; color:var(--text-faint); }

.kpi-grid{ display:grid; grid-template-columns:repeat(auto-fit, minmax(170px,1fr)); gap:1px;
  background:var(--border); border:1px solid var(--border); border-radius:10px; overflow:hidden;
  box-shadow:var(--shadow); }
.kpi{ background:var(--surface); padding:1.05rem 1.15rem; display:flex; flex-direction:column; gap:0.35rem; }
.kpi .label{ font-size:0.7rem; letter-spacing:0.04em; text-transform:uppercase; color:var(--text-faint); font-weight:600; }
.kpi .value{ font-family:"IBM Plex Mono",monospace; font-size:1.55rem; font-weight:600; letter-spacing:-0.01em; }
.kpi .sub{ font-size:0.76rem; color:var(--text-dim); }

.panel{ background:var(--surface); border:1px solid var(--border); border-radius:10px;
  padding:1.25rem 1.35rem; box-shadow:var(--shadow); }

.legend{ display:flex; gap:1.1rem; font-size:0.78rem; color:var(--text-dim); margin-bottom:0.9rem; flex-wrap:wrap; }
.legend span{ display:inline-flex; align-items:center; gap:0.4rem; }
.swatch{ width:10px; height:10px; border-radius:2px; display:inline-block; }

#trend-chart { width:100%; height:auto; overflow: visible; }
#trend-chart text { font-family:"IBM Plex Mono", monospace; fill: var(--text-faint); font-size: 9.5px; }
#trend-chart .gridline { stroke: var(--border); stroke-width: 1; stroke-dasharray: 2,3; }
#trend-chart .axis { stroke: var(--border); stroke-width: 1; }
#trend-chart .seg-answered { fill: var(--good); }
#trend-chart .seg-refused { fill: var(--bad); }
#trend-chart .seg-conceded { fill: var(--accent); }

.intent-list{ display:flex; flex-direction:column; gap:0.6rem; }
.intent-row{ display:grid; grid-template-columns:150px 1fr 42px; align-items:center; gap:0.7rem; }
.intent-row .name{ font-family:"IBM Plex Mono",monospace; font-size:0.82rem; color:var(--text-dim); }
.intent-row .track{ height:9px; background:var(--surface-2); border-radius:5px; overflow:hidden; }
.intent-row .fill{ height:100%; background:var(--accent); border-radius:5px; }
.intent-row .count{ font-family:"IBM Plex Mono",monospace; font-size:0.8rem; text-align:right; color:var(--text-dim); }

#error{ display:none; background:var(--bad-soft); color:var(--bad); border-radius:8px;
  padding:0.7rem 1rem; font-size:0.85rem; }
#empty{ display:none; color:var(--text-faint); font-size:0.88rem; padding:0.4rem 0; }

.token-gate{ display:flex; flex-direction:column; gap:0.7rem; max-width:420px; }
.token-gate input{ font-family:"IBM Plex Mono",monospace; font-size:0.88rem; padding:0.55rem 0.7rem;
  border:1px solid var(--border); border-radius:7px; background:var(--surface); color:var(--text); }
.token-gate button{ font-family:"IBM Plex Sans",sans-serif; font-weight:600; font-size:0.86rem;
  padding:0.55rem 0.9rem; border-radius:7px; border:none; background:var(--accent); color:#fff; cursor:pointer; }
.token-gate .hint{ font-size:0.78rem; color:var(--text-faint); }

footer{ border-top:1px solid var(--border); padding-top:1rem; font-size:0.78rem; color:var(--text-faint); }
footer code{ font-family:"IBM Plex Mono",monospace; }
</style>
</head>
<body>
<div class="wrap">

  <header>
    <span class="eyebrow">Showroom Copilot &middot; Internal</span>
    <h1>Live Metrics</h1>
    <p class="subtitle">Real query volume, refusal rate, concession rate, and hallucination rate
      from <span class="mono">query_events</span> — every <span class="mono">POST /chat</span>
      call, as it happens. Never the query or response text itself, only the classification.
      "Hallucination rate" is the model's first draft, before verify_grounding's regenerate-once
      check — an accepted answer can never itself carry one by construction, so this is measured
      on the attempt, not the response the consultant actually saw.</p>
  </header>

  <div id="error"></div>

  <div id="gate" class="token-gate" style="display:none;">
    <label for="token-input" style="font-size:0.85rem; font-weight:600;">Admin token</label>
    <input id="token-input" type="password" placeholder="x-admin-token value" autocomplete="off">
    <button id="token-submit">Load metrics</button>
    <span class="hint">Or open this page as <code class="mono">/admin/dashboard?token=...</code></span>
  </div>

  <div id="content" style="display:none; flex-direction:column; gap:2rem;">

    <section class="kpi-grid" id="kpi-grid"></section>

    <section>
      <div class="section-head">
        <h2>Volume, refusal &amp; concession over time</h2>
        <span class="hint">stacked by outcome, per day</span>
      </div>
      <div class="panel">
        <div class="legend">
          <span><i class="swatch" style="background:var(--good);"></i>answered</span>
          <span><i class="swatch" style="background:var(--accent);"></i>conceded</span>
          <span><i class="swatch" style="background:var(--bad);"></i>refused</span>
        </div>
        <svg id="trend-chart" viewBox="0 0 640 220"></svg>
        <div id="empty">No queries logged yet — ask the assistant something, then reload.</div>
      </div>
    </section>

    <section>
      <div class="section-head">
        <h2>By intent class</h2>
      </div>
      <div class="panel">
        <div class="intent-list" id="intent-list"></div>
      </div>
    </section>

  </div>

</div>

<script>
function fmtPct(x) { return (x * 100).toFixed(1) + "%"; }
function esc(s) { return String(s).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c])); }

function renderKpis(totals, dailyCost) {
  const grid = document.getElementById("kpi-grid");
  grid.innerHTML = `
    <div class="kpi"><span class="label">Total queries</span>
      <span class="value">${totals.n}</span><span class="sub">all time</span></div>
    <div class="kpi"><span class="label">Refusal rate</span>
      <span class="value" style="color:var(--bad);">${fmtPct(totals.refusal_rate)}</span>
      <span class="sub">of all queries</span></div>
    <div class="kpi"><span class="label">Concession rate</span>
      <span class="value" style="color:var(--accent);">${fmtPct(totals.concession_rate)}</span>
      <span class="sub">honest-weakness objections</span></div>
    <div class="kpi"><span class="label">Hallucination rate</span>
      <span class="value" style="color:var(--warn);">${fmtPct(totals.first_attempt_hallucination_rate)}</span>
      <span class="sub">first draft uncited/miscited, of ${totals.generated_n} generated</span></div>
    <div class="kpi"><span class="label">Hallucination &rarr; refusal</span>
      <span class="value" style="color:var(--bad);">${fmtPct(totals.hallucination_refusal_rate)}</span>
      <span class="sub">reached the user as a refusal, of all queries</span></div>
    <div class="kpi"><span class="label">Est. cost</span>
      <span class="value">$${dailyCost.toFixed(4)}</span><span class="sub">all time, LLM calls</span></div>
  `;
}

function renderIntents(byIntent) {
  const entries = Object.entries(byIntent).sort((a, b) => b[1] - a[1]);
  const max = Math.max(1, ...entries.map(([, c]) => c));
  const list = document.getElementById("intent-list");
  if (entries.length === 0) {
    list.innerHTML = '<span style="color:var(--text-faint); font-size:0.85rem;">No queries yet.</span>';
    return;
  }
  list.innerHTML = entries.map(([intent, count]) => `
    <div class="intent-row">
      <span class="name">${esc(intent)}</span>
      <div class="track"><div class="fill" style="width:${(count / max * 100).toFixed(1)}%"></div></div>
      <span class="count">${count}</span>
    </div>
  `).join("");
}

function renderTrend(daily) {
  const svg = document.getElementById("trend-chart");
  const empty = document.getElementById("empty");
  if (!daily.length) { svg.style.display = "none"; empty.style.display = "block"; return; }
  svg.style.display = "block"; empty.style.display = "none";

  const W = 640, H = 220, padL = 34, padB = 26, padT = 12, padR = 12;
  const plotW = W - padL - padR, plotH = H - padT - padB;
  const maxN = Math.max(1, ...daily.map(d => d.n));
  const barGap = 10;
  const barW = Math.min(46, (plotW / daily.length) - barGap);
  const step = plotW / daily.length;

  let svgText = "";
  // gridlines
  for (const frac of [0, 0.5, 1]) {
    const y = padT + plotH * (1 - frac);
    svgText += `<line class="gridline" x1="${padL}" y1="${y}" x2="${W - padR}" y2="${y}"/>`;
    svgText += `<text x="${padL - 6}" y="${y + 3}" text-anchor="end">${Math.round(maxN * frac)}</text>`;
  }
  svgText += `<line class="axis" x1="${padL}" y1="${padT + plotH}" x2="${W - padR}" y2="${padT + plotH}"/>`;

  daily.forEach((d, i) => {
    const x = padL + step * i + (step - barW) / 2;
    const refused = Math.round(d.n * d.refusal_rate);
    const conceded = Math.round(d.n * d.concession_rate);
    const answered = Math.max(0, d.n - refused - conceded);
    const scale = plotH / maxN;
    let y = padT + plotH;
    for (const [count, cls] of [[refused, "seg-refused"], [conceded, "seg-conceded"], [answered, "seg-answered"]]) {
      const h = count * scale;
      y -= h;
      if (h > 0) svgText += `<rect class="${cls}" x="${x}" y="${y}" width="${barW}" height="${h}"></rect>`;
    }
    const label = d.date.slice(5); // MM-DD
    svgText += `<text x="${x + barW / 2}" y="${padT + plotH + 16}" text-anchor="middle">${label}</text>`;
  });

  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.innerHTML = svgText;
}

function showError(msg) {
  const el = document.getElementById("error");
  el.textContent = msg;
  el.style.display = "block";
}

function loadMetrics(token) {
  document.getElementById("error").style.display = "none";
  fetch("/admin/metrics", { headers: { "x-admin-token": token } })
    .then(r => {
      if (r.status === 403) throw new Error("FORBIDDEN");
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    })
    .then(data => {
      document.getElementById("gate").style.display = "none";
      document.getElementById("content").style.display = "flex";
      const totalCost = data.daily.reduce((sum, d) => sum + d.cost_usd, 0);
      renderKpis(data.totals, totalCost);
      renderTrend(data.daily);
      renderIntents(data.by_intent);
      try { sessionStorage.setItem("sc_admin_token", token); } catch (e) {}
    })
    .catch(e => {
      document.getElementById("content").style.display = "none";
      document.getElementById("gate").style.display = "flex";
      if (e.message === "FORBIDDEN") {
        showError("That token was rejected. Check x-admin-token / ADMIN_INGEST_TOKEN.");
      } else {
        showError("Failed to load metrics: " + e.message);
      }
    });
}

const params = new URLSearchParams(window.location.search);
let token = params.get("token");
if (!token) { try { token = sessionStorage.getItem("sc_admin_token"); } catch (e) {} }

if (token) {
  loadMetrics(token);
} else {
  document.getElementById("gate").style.display = "flex";
}

document.getElementById("token-submit").addEventListener("click", () => {
  const val = document.getElementById("token-input").value;
  if (val) loadMetrics(val);
});
document.getElementById("token-input").addEventListener("keydown", (e) => {
  if (e.key === "Enter") document.getElementById("token-submit").click();
});
</script>
</body>
</html>
"""


@router.get("/admin/dashboard", response_class=HTMLResponse)
def admin_dashboard(token: str | None = Query(default=None)) -> str:
    """Static HTML shell for T8.2 — no server-side templating of the token
    into the page (it's passed to `/admin/metrics` client-side via header,
    same gate as every other `/admin/*` route), so this route itself needs
    no auth check: it renders nothing sensitive on its own, only a page that
    asks the browser to fetch the real data with a token the URL supplies
    (or one typed into the on-page form, kept in `sessionStorage` only —
    never sent anywhere but this page's own `/admin/metrics` calls).
    """
    return _DASHBOARD_HTML
