"""Tone Stylist Agent: turns a tone name into a checkable style contract.

The contract is the mechanism that makes tone testable. "Friendly" cannot be
verified by the review agent; "greeting must be exactly 'Hi Priya,', never use
'per my last email', keep sentences short" can. Both the writer and the reviewer
read the same contract, so they cannot disagree about what the tone meant.
"""

from __future__ import annotations

from typing import Any

from .. import prompts
from ..config import load_tone_sample
from ..integrations.router import ModelRouter
from ..state import EmailState, ToneSpec
from .common import emit_status, first_nonempty, merge_trace

DEFAULT_TONE = "friendly"


def tone_stylist_agent(state: EmailState, router: ModelRouter) -> dict[str, Any]:
    parsed = state.get("parsed") or {}
    intent = state.get("intent") or {}
    profile = state.get("profile") or {}

    tone = first_nonempty(
        state.get("requested_tone"),
        profile.get("default_tone"),
        DEFAULT_TONE,
    )
    assert tone is not None  # DEFAULT_TONE is a non-empty literal
    tone = tone.lower()

    emit_status(f"Building the {tone} style contract")
    before = len(router.calls)

    result = router.complete(
        task="tone",
        system=prompts.TONE_SYSTEM,
        user=prompts.tone_user(
            tone=tone,
            tone_sample=load_tone_sample(tone),
            intent=str(intent.get("intent") or "information"),
            parsed=parsed,
            style_evidence=profile.get("style_evidence") or [],
        ),
        schema=ToneSpec,
    )
    spec: ToneSpec = result.parsed  # type: ignore[assignment]

    return {
        "tone_spec": spec.model_dump(mode="json"),
        "trace": merge_trace(router, before),
    }
