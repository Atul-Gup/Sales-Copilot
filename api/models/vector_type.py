"""A dense-embedding column that is a real `pgvector` column on Postgres and
a portable JSON-encoded fallback everywhere else (SQLite, in this project's
test suite and the in-memory eval corpus from T3.6).

This sandbox has no live Postgres (see T3.6's notes on why `run_eval.py`
builds its corpus against SQLite), so `document_chunks.embedding` cannot be
exercised as a real pgvector column here — cosine-distance queries against
it are T4.2b's job, against a real Postgres instance. This type just makes
sure the same model and the same ingested data work in both places.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import Text
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator


class EmbeddingVector(TypeDecorator[list[float]]):
    impl = Text
    cache_ok = True

    def __init__(self, dim: int, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.dim = dim

    def load_dialect_impl(self, dialect: Dialect) -> Any:
        if dialect.name == "postgresql":
            from pgvector.sqlalchemy import Vector

            return dialect.type_descriptor(Vector(self.dim))
        return dialect.type_descriptor(Text())

    def process_bind_param(self, value: list[float] | None, dialect: Dialect) -> Any:
        if value is None:
            return None
        if dialect.name == "postgresql":
            return value
        return json.dumps(value)

    def process_result_value(self, value: Any, dialect: Dialect) -> list[float] | None:
        if value is None:
            return None
        if dialect.name == "postgresql":
            return list(value)
        return list(json.loads(value))
