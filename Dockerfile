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

RUN pip install --no-cache-dir .

EXPOSE 8000

# Run migrations against whatever DATABASE_URL is configured, then start the
# API. `alembic upgrade head` is a no-op when already current, so this is
# safe to run on every boot rather than needing a separate release step.
CMD ["sh", "-c", "alembic upgrade head && uvicorn api.main:app --host 0.0.0.0 --port 8000"]
