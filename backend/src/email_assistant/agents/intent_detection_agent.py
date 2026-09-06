"""Intent Detection Agent: classifies the email's purpose.

The intent drives structure downstream — an apology opens differently from a
request — so it is worth a dedicated node rather than a field on ParsedInput.
Splitting it also means the classification can be routed to a cheap model while
the draft stays on a strong one, which is the whole premise of the cost profile.
"""

from __future__ import annotations

from typing import Any

from .. import prompts
from ..integrations.router import ModelRouter
from ..state import EmailState, Intent, IntentResult
from .common import emit_status, merge_trace


def intent_detection_agent(state: EmailState, router: ModelRouter) -> dict[str, Any]:
    parsed = state.get("parsed") or {}

    # An intent chosen in the UI is a decision, not a hypothesis. Skip the call
    # entirely rather than asking a model to confirm what the user already said.
    requested = (state.get("requested_intent") or "").strip().lower()
    if requested and requested != "auto":
        try:
            chosen = Intent(requested)
        except ValueError:
            chosen = None
        if chosen is not None:
            emit_status(f"Using the requested intent: {chosen.value}")
            return {
                "intent": IntentResult(
                    intent=chosen,
                    confidence=1.0,
                    rationale="Selected explicitly by the user.",
                ).model_dump(mode="json")
            }

    emit_status("Working out what this email is for")
    before = len(router.calls)

    result = router.complete(
        task="intent",
        system=prompts.INTENT_SYSTEM,
        user=prompts.intent_user(state.get("raw_prompt") or "", parsed),
        schema=IntentResult,
    )
    intent: IntentResult = result.parsed  # type: ignore[assignment]

    return {
        "intent": intent.model_dump(mode="json"),
        "trace": merge_trace(router, before),
    }
