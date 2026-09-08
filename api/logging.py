"""api/logging.py — structlog configuration (T8.1).

`api/llm/client.py` and `api/llm/embeddings.py` already emit structured
`logger.info(...)`/`logger.error(...)` calls (cost, tokens, latency), and
`api/services/retrieve.py`/`api/services/pipeline.py` add retrieval and
per-query `chat_answer` events alongside them — but structlog was never
configured anywhere, so every one of those calls was falling back to
structlog's interactive-console default renderer, not JSON. That's fine for
a local terminal but useless for T8.2's dashboard, which needs to parse log
lines as structured events, not pretty-printed text. `configure_logging()`
switches the renderer to one JSON object per line (with an ISO-8601
timestamp and level attached) and does nothing else — no request-id
middleware, no external log shipper; Railway/Vercel already capture stdout,
which is where every line goes.

Called once, at import time, from `api/main.py` — before any router module
that might log something during import.
"""

from __future__ import annotations

import logging

import structlog


def configure_logging() -> None:
    logging.basicConfig(format="%(message)s", level=logging.INFO)
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
