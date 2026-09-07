"""`/objection/stream` endpoint — Server-Sent Events wrapper over
`api.objection.stream.stream_objection_response` (T6.3).

Each `StreamEvent` from that generator is forwarded to the client as one SSE
frame (`event: <type>\ndata: <json>\n\n`), in the order produced:
`category` first, then either a single `abstained` event, or a sequence of
`token` events followed by exactly one `done` or `refused` event. A client
should render `token` text incrementally as it arrives and treat a
`refused` event as a signal to discard whatever partial text it has shown
so far — see `api/objection/stream.py`'s docstring for why streaming
can't undo already-sent tokens the way the non-streaming graph's
regenerate-once-then-refuse cycle can.

`get_llm_client`/`get_embedding_client` construct their vendor clients
lazily, inside the request, not at import time — `LLMClient()` and
`EmbeddingClient()` both read `OPENAI_API_KEY` from the environment and raise
if unset, so constructing either at module scope would crash app startup in
any environment without that key configured (this sandbox included). Tests
override both dependencies with fakes, the same pattern `api.db.get_db`
already establishes for the database session.
"""

from __future__ import annotations

import json
from collections.abc import Generator
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.db import get_db
from api.llm.client import LLMClient
from api.llm.embeddings import EmbeddingClient
from api.objection.stream import stream_objection_response

router = APIRouter()


def get_llm_client() -> LLMClient:
    return LLMClient()


def get_embedding_client() -> EmbeddingClient:
    return EmbeddingClient()


class ObjectionRequest(BaseModel):
    objection_text: str
    context: dict[str, Any] = {}


def _format_sse(event_type: str, data: dict[str, Any]) -> str:
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"


def _sse_events(
    llm: LLMClient,
    embedder: EmbeddingClient,
    db: Session,
    objection_text: str,
    context: dict[str, Any],
) -> Generator[str, None, None]:
    for event in stream_objection_response(llm, embedder, db, objection_text, context):
        event_type = event["type"]
        data: dict[str, Any] = {k: v for k, v in event.items() if k != "type"}
        if "response" in data:
            data["response"] = data["response"].__dict__
        yield _format_sse(event_type, data)


@router.post("/objection/stream")
def objection_stream(
    request: ObjectionRequest,
    db: Session = Depends(get_db),  # noqa: B008
    llm: LLMClient = Depends(get_llm_client),  # noqa: B008
    embedder: EmbeddingClient = Depends(get_embedding_client),  # noqa: B008
) -> StreamingResponse:
    return StreamingResponse(
        _sse_events(llm, embedder, db, request.objection_text, request.context),
        media_type="text/event-stream",
    )
