"""FastAPI application.

Generation streams over Server-Sent Events. SSE rather than WebSockets because
the traffic is one-directional and short-lived: the client posts a request and
reads events until the run ends. A WebSocket would add reconnection and
heartbeat handling for a stream that lasts a few seconds.

The graph is synchronous, and FastAPI's EventSourceResponse accepts a sync
iterable and drives it through a threadpool, so no part of the pipeline needs an
async rewrite to stream.
"""

from __future__ import annotations

import os
from typing import Any, Iterator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.sse import EventSourceResponse, ServerSentEvent

from ..config import get_routing_config, get_settings
from ..integrations.router import ModelRouter
from ..memory.profile_store import ProfileStore
from ..state import MAX_REVISIONS
from .events import agent_catalog, generate_events
from .schemas import (
    ConfigResponse,
    EditRequest,
    GenerateRequest,
    ProfileResponse,
    ProfileUpdate,
    config_payload,
)

app = FastAPI(
    title="AI-Powered Email Assistant",
    version="1.0.0",
    description="Multi-agent email drafting over LangGraph with cross-provider model routing.",
)

# The Vite dev server runs on a different origin, as does the deployed frontend
# (e.g. on Vercel) when the API is hosted separately. Extra production origins
# are supplied via CORS_ORIGINS as a comma-separated list.
_default_origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:4173",
]
_extra_origins = [
    o.strip() for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_default_origins + _extra_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "OPTIONS"],
    allow_headers=["*"],
)


def _store() -> ProfileStore:
    return ProfileStore()


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/config", response_model=ConfigResponse)
def read_config() -> ConfigResponse:
    """What the front end needs to render its controls and badges."""
    settings = get_settings()
    routing = get_routing_config()
    router = ModelRouter(usage_log_path=None)
    return config_payload(
        offline=settings.offline,
        active_profile=router.profile,
        routing_profiles=routing.profile_names,
        providers=router.provider_status(),
        agents=agent_catalog(),
        max_revisions=MAX_REVISIONS,
    )


@app.post("/api/generate", response_class=EventSourceResponse, response_model=None)
def generate(request: GenerateRequest) -> Iterator[ServerSentEvent]:
    """Stream a generation run as Server-Sent Events.

    A plain function returning a generator, not a generator function itself.
    That distinction matters: the validation below has to run before the response
    starts, and a `yield` anywhere in this body would defer the whole thing until
    the first frame is pulled — by which point the status line is already sent
    and an HTTPException can no longer become a 400.

    response_model=None because the return annotation is a stream, not a body
    FastAPI should try to serialize.
    """
    routing = get_routing_config()
    profile = request.routing_profile or None
    if profile is not None and profile not in routing.profile_names:
        raise HTTPException(
            status_code=400,
            detail=f"unknown routing profile {profile!r}; available: {routing.profile_names}",
        )

    if not request.prompt.strip():
        raise HTTPException(status_code=400, detail="prompt is empty")

    def stream() -> Iterator[ServerSentEvent]:
        for name, payload in generate_events(
            prompt=request.prompt,
            tone=request.tone,
            intent=request.intent,
            recipient=request.recipient,
            length=request.length,
            user_id=request.user_id,
            routing_profile=profile,
            store=_store(),
        ):
            yield ServerSentEvent(data=payload, event=name)

    return stream()


@app.get("/api/profile/{user_id}", response_model=ProfileResponse)
def read_profile(user_id: str) -> ProfileResponse:
    store = _store()
    profile = store.get(user_id)
    profile["style_evidence_count"] = len(store.style_evidence(user_id, limit=99))
    return ProfileResponse(profile=profile)


@app.put("/api/profile/{user_id}", response_model=ProfileResponse)
def update_profile(user_id: str, update: ProfileUpdate) -> ProfileResponse:
    # exclude_unset so a client sending only `name` does not blank the rest.
    changes: dict[str, Any] = update.model_dump(exclude_unset=True, exclude_none=True)
    return ProfileResponse(profile=_store().save(user_id, changes))


@app.get("/api/profiles")
def list_profiles() -> dict[str, list[str]]:
    return {"users": _store().list_users()}


@app.post("/api/drafts/{draft_id}/edits")
def save_edit(draft_id: str, request: EditRequest) -> dict[str, Any]:
    """Record how the user rewrote a draft, so the stylist can learn from it."""
    if request.original_body.strip() == request.edited_body.strip():
        # Nothing changed, so there is nothing to learn. Saying so beats storing
        # a no-op the stylist would later have to filter out.
        return {
            "saved": False,
            "reason": "no changes to learn from",
            "evidence_count": 0,
        }

    store = _store()
    store.record_edit(
        request.user_id,
        draft_id=draft_id,
        original_body=request.original_body,
        edited_body=request.edited_body,
        subject=request.subject,
    )
    return {
        "saved": True,
        "evidence_count": len(store.style_evidence(request.user_id, limit=99)),
    }
