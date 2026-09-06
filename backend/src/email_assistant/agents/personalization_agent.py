"""Personalization Agent: loads the sender's profile and their real writing style.

The one agent that makes no model call. Everything it does is a lookup, and
asking a model to read a JSON file back to us would add latency, cost, and a
chance of hallucinating a signature the user never set.

It runs before the tone stylist because the stylist needs the user's edit history
to build a style contract from how they actually write, rather than from a
generic exemplar.
"""

from __future__ import annotations

from typing import Any, Optional

from ..memory.profile_store import ProfileStore
from ..state import EmailState
from .common import emit_status


def personalization_agent(
    state: EmailState,
    store: Optional[ProfileStore] = None,
) -> dict[str, Any]:
    emit_status("Loading your profile and past edits")
    store = store or ProfileStore()

    user_id = state.get("user_id") or "default"
    profile = store.get(user_id)
    profile["style_evidence"] = store.style_evidence(user_id)

    return {"profile": profile}
