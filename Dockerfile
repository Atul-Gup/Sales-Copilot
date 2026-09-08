# Dockerfile — the API only (T7.4). The web/ Next.js app deploys separately
# to Vercel, which builds straight from the repo and doesn't need this image.
FROM python:3.11-slim

WORKDIR /app

# libpq for psycopg (binary wheels cover most of it, but the runtime linker
# still wants libpq.so present on slim images).
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY api ./api
COPY ingest ./ingest
COPY evals ./evals
COPY migrations ./migrations
COPY alembic.ini ./
COPY scripts ./scripts
# The source PDFs/spreadsheets POST /admin/ingest (T7.4) reads — this is the
# only place that can reach the database's internal hostname, so ingestion
# has to happen from inside this image rather than from a local machine.
# Only the two subdirectories ingest/product_docs.py and
# ingest/service_centres.py actually read — data/sources/_archive (superseded
# source PDFs, docs/CORPUS.md) is 90MB of dead weight this image never needs.
COPY data/sources/products ./data/sources/products
COPY ["data/sources/service centres", "./data/sources/service centres"]

RUN pip install --no-cache-dir .

EXPOSE 8000

# scripts/bootstrap_db.py runs `alembic upgrade head` (a no-op once already
# current) and only falls back to resetting alembic's tracking table if that
# fails — see that script's docstring for why a plain `alembic upgrade head`
# alone isn't safe here on this database.
CMD ["sh", "-c", "python -m scripts.bootstrap_db && uvicorn api.main:app --host 0.0.0.0 --port 8000"]
