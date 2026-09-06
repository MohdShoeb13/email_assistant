"""Request and response bodies for the HTTP API."""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from ..state import Intent, Tone


class GenerateRequest(BaseModel):
    """A request to draft an email."""

    prompt: str = Field(min_length=1, max_length=8000)
    tone: Optional[str] = None
    intent: str = "auto"
    recipient: Optional[str] = None
    length: Literal["short", "medium", "long"] = "medium"
    user_id: str = "default"
    routing_profile: Optional[str] = None


class ProfileUpdate(BaseModel):
    """Editable profile fields.

    An explicit allow-list rather than a free-form dict: these values are
    interpolated into prompts, so the set of things a client can put there is
    part of the API contract, not an implementation detail.
    """

    name: Optional[str] = Field(None, max_length=120)
    role: Optional[str] = Field(None, max_length=120)
    company: Optional[str] = Field(None, max_length=120)
    signature: Optional[str] = Field(None, max_length=400)
    default_tone: Optional[str] = None


class EditRequest(BaseModel):
    """The user's rewrite of a generated draft.

    `original_body` is sent back by the client rather than looked up server-side,
    because the diff must be against the text the user actually edited — which
    may be an older draft if they left the tab open.
    """

    user_id: str = "default"
    original_body: str
    edited_body: str
    subject: str = ""


class ProviderInfo(BaseModel):
    name: str
    available: bool


class ConfigResponse(BaseModel):
    """Everything the front end needs to render its controls."""

    offline: bool
    active_profile: str
    routing_profiles: list[str]
    providers: list[ProviderInfo]
    tones: list[str]
    intents: list[str]
    lengths: list[str]
    agents: list[dict[str, str]]
    max_revisions: int


def config_payload(
    *,
    offline: bool,
    active_profile: str,
    routing_profiles: list[str],
    providers: dict[str, bool],
    agents: list[dict[str, str]],
    max_revisions: int,
) -> ConfigResponse:
    return ConfigResponse(
        offline=offline,
        active_profile=active_profile,
        routing_profiles=routing_profiles,
        providers=[ProviderInfo(name=n, available=a) for n, a in sorted(providers.items())],
        tones=[t.value for t in Tone],
        intents=["auto"] + [i.value for i in Intent],
        lengths=["short", "medium", "long"],
        agents=agents,
        max_revisions=max_revisions,
    )


class ProfileResponse(BaseModel):
    profile: dict[str, Any]
