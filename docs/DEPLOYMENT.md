# DEPLOYMENT — Showroom Copilot (T7.4)

This repo ships deploy-ready config (`Dockerfile`, `fly.toml`) but no live
deployment has been created from this sandbox — that needs your own
Fly/Railway and Vercel accounts and API keys, none of which this
environment has or should fabricate. Everything below is the exact command
sequence to run yourself.

## API — Fly.io (primary path)

Prerequisite: [Fly CLI installed and logged in](https://fly.io/docs/hands-on/install-flyctl/) (`fly auth login`).

1. **Create the Postgres database** (pgvector required — this project's
   `document_chunks` table uses it, per `docs/ARCHITECTURE.md`):
   ```
   fly postgres create --name showroom-copilot-db --region bom
   ```
   Fly's managed Postgres doesn't enable `pgvector` by default. Connect and
   enable it once:
   ```
   fly postgres connect -a showroom-copilot-db
   CREATE EXTENSION IF NOT EXISTS vector;
   ```

2. **Adopt the app** (`fly.toml` at the repo root already names the app
   `showroom-copilot-api` and region `bom` — Mumbai, closest to the Volvo
   India dealerships this tool is built for):
   ```
   fly launch --no-deploy --copy-config --name showroom-copilot-api
   ```

3. **Attach the database** (sets `DATABASE_URL` as a Fly secret automatically):
   ```
   fly postgres attach showroom-copilot-db -a showroom-copilot-api
   ```

4. **Set the remaining secrets** — everything `api/settings.py` and
   `api/llm/*.py` read from the environment:
   ```
   fly secrets set \
     ANTHROPIC_API_KEY=sk-ant-... \
     OPENAI_API_KEY=sk-... \
     CORS_ALLOW_ORIGINS='["https://<your-vercel-app>.vercel.app"]' \
     -a showroom-copilot-api
   ```
   `CORS_ALLOW_ORIGINS` must be valid JSON (a list of origin strings) — that's
   how `pydantic-settings` parses a `list[str]` field from an env var. Update
   this once the Vercel URL from the web deploy below is known; the default
   in `api/settings.py` (`http://localhost:3000`) only covers local dev.

5. **Deploy**:
   ```
   fly deploy
   ```
   The image's `CMD` (see `Dockerfile`) runs `alembic upgrade head` before
   starting `uvicorn`, so every deploy migrates the database to the latest
   schema automatically — no separate release step needed.

6. **Ingest the corpus** — the app boots with an empty database; nothing in
   the Dockerfile runs `ingest/*.py` automatically, since re-running ingest
   on every deploy would be wasteful and ingest is idempotent-by-design but
   not something to run unattended on every boot. Run it once against the
   deployed database:
   ```
   fly ssh console -a showroom-copilot-api -C "python -m ingest.volvo"
   # repeat for ingest.bmw, ingest.mercedes, ingest.audi,
   # ingest.euroncap, ingest.service_centres
   ```

7. **Verify**: `curl https://showroom-copilot-api.fly.dev/health` should
   return `{"status": "ok"}`.

## API — Railway (alternative)

Railway auto-detects the root `Dockerfile`, so no separate config file is
needed.

1. `railway login`, then `railway init` in the repo root.
2. Add a Postgres plugin from the Railway dashboard (or `railway add`),
   which sets `DATABASE_URL` automatically. Enable `pgvector` the same way
   as the Fly instructions above (`railway connect postgres`, then
   `CREATE EXTENSION IF NOT EXISTS vector;`).
3. Set the same secrets as step 4 above via `railway variables set` or the
   dashboard: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `CORS_ALLOW_ORIGINS`.
4. `railway up` to deploy. Run the ingest step the same way, via
   `railway run python -m ingest.volvo` (and the rest).

## Web — Vercel

Prerequisite: [Vercel CLI](https://vercel.com/docs/cli) installed and
logged in (`vercel login`), or connect the GitHub repo directly from the
Vercel dashboard (Root Directory: `web/`) — either works, since `web/` is a
standard Next.js App Router project with no custom build config needed.

1. From `web/`:
   ```
   cd web
   vercel link
   vercel env add NEXT_PUBLIC_API_BASE_URL production
   # paste the Fly/Railway API URL from above, e.g. https://showroom-copilot-api.fly.dev
   vercel deploy --prod
   ```
2. Once you have the resulting `https://<app>.vercel.app` URL, go back and
   update the API's `CORS_ALLOW_ORIGINS` secret (step 4 above) to include
   it, then redeploy the API (`fly deploy` / `railway up`) — CORS is
   allow-listed by exact origin, so the API rejects the browser's requests
   until this is set correctly in both directions.

## Post-deploy checklist

- [ ] `GET /health` on the API URL returns `{"status": "ok"}`
- [ ] The Vercel URL's home page shows "Connected to the API" (the status
      pill built in T7.1) rather than "Can't reach the API"
- [ ] `/compare` populates its vehicle pickers (confirms ingest ran and
      `/variants` has rows)
- [ ] `/objection` streams a response for a real objection (confirms
      `ANTHROPIC_API_KEY`/`OPENAI_API_KEY` are valid — this is the first time
      either endpoint is exercised against a real vendor call anywhere in
      this project; every eval and test up to this point used a scripted
      proxy because no live keys existed in the development sandbox)
