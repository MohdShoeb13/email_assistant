"""Routing and Memory Agent: the terminal node.

The brief gives this agent three jobs — manage fallback flow, log drafts, and
store profile memory. The first of those lives one layer down in
integrations/router.py, because model fallback has to happen inside every agent's
call, not once at the end. What is left here is the part that genuinely belongs
at the end of the run: settle the final status, persist the draft, and hand the
caller a complete record of which models served it.

It makes no model call. Deciding whether a run passed is arithmetic on the
review verdict, and persistence is a file write.
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

from ..memory.profile_store import ProfileStore
from ..state import MAX_REVISIONS, EmailState
from .common import emit_status


def router_agent(
    state: EmailState,
    store: Optional[ProfileStore] = None,
) -> dict[str, Any]:
    store = store or ProfileStore()

    draft = state.get("draft") or {}
    review = state.get("review") or {}
    attempts = int(state.get("attempts") or 0)
    passed = bool(review.get("passed"))

    if not draft:
        emit_status("Finished without a draft")
        return {"status": "failed"}

    if passed:
        status = "complete"
        emit_status("Draft approved")
    else:
        # Out of revisions but holding a draft. Hand it over flagged rather than
        # failing: a draft with known issues is more use to the user than none,
        # and the UI shows exactly what the reviewer objected to.
        status = "needs_review"
        emit_status(f"Returning the best draft after {attempts} of {MAX_REVISIONS + 1} passes")

    draft_id = state.get("session_id") or uuid.uuid4().hex[:12]
    tone = (state.get("tone_spec") or {}).get("tone") or ""
    intent = (state.get("intent") or {}).get("intent") or ""

    try:
        store.record_draft(
            state.get("user_id") or "default",
            draft_id=draft_id,
            subject=draft.get("subject", ""),
            body=draft.get("body", ""),
            tone=str(tone),
            intent=str(intent),
        )
    except OSError as exc:
        # Losing the history entry must not lose the draft the user is waiting on.
        return {"status": status, "draft_id": draft_id, "errors": [f"Could not save draft history: {exc}"]}

    return {"status": status, "draft_id": draft_id}
