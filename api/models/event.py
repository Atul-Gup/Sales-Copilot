from __future__ import annotations

import datetime

from sqlalchemy import Boolean, DateTime, Float, String
from sqlalchemy.orm import Mapped, mapped_column

from api.models.base import Base


class QueryEvent(Base):
    """One row per `pipeline.answer()` call (T8.2).

    The dashboard's data source: `api/services/pipeline.py::answer()` logs a
    structured `chat_answer` event on every call (T8.1) for stdout/log-based
    observability, but Railway's captured stdout isn't queryable for
    aggregates. This table is the same event, persisted, so `/admin/metrics`
    (`api/routers/admin.py`) can actually compute query volume by intent,
    refusal/concession rate over time, and cost per day with plain SQL
    `GROUP BY` instead of parsing logs.

    Never stores the query or response text — same reasoning as the
    `chat_answer` log event: consultant-entered queries can name a real
    customer's specifics, and nothing here needs the content, only the
    classification/outcome.
    """

    __tablename__ = "query_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.UTC), index=True
    )
    intent: Mapped[str | None] = mapped_column(String, nullable=True)
    refused: Mapped[bool] = mapped_column(Boolean, nullable=False)
    conceded: Mapped[bool] = mapped_column(Boolean, nullable=False)
    blocked_by_input_guardrail: Mapped[str | None] = mapped_column(String, nullable=True)
    top_score: Mapped[float] = mapped_column(Float, nullable=False)
    latency_ms: Mapped[float] = mapped_column(Float, nullable=False)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
