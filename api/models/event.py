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
    # Why the answer was refused, mirroring AnswerResult.refusal_reason
    # (api/services/pipeline.py): "no_answer_outside_corpus" (nothing to
    # generate from) vs "grounding_violation" (generation ran but couldn't
    # produce a verifiably-cited answer) are different failure modes with
    # different fixes, so the dashboard needs to tell them apart rather than
    # lumping every refusal into one rate. Null when not refused.
    refusal_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    # Whether verify_grounding's *first* generation attempt had an uncited
    # or wrong-chunk claim, whether or not the second attempt then fixed it
    # or the query was ultimately refused. By construction (verify.py's
    # regenerate-once-then-refuse loop), an *accepted* response can never
    # itself carry a violation — so this is the only place a genuine
    # hallucination/miscitation rate can be measured at all; a rate computed
    # over accepted responses alone would always read 0%. Null when no
    # generation happened this call (blocked, refused pre-retrieval, or
    # conceded) — there was no attempt to have a violation.
    first_attempt_had_violation: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
