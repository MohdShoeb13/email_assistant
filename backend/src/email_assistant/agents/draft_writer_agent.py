"""Draft Writer Agent: writes the email.

The only node that runs more than once. On a revision pass it receives the
reviewer's fix_instructions and is told to change nothing else — a full rewrite
would discard the parts the reviewer already accepted and can easily introduce a
new problem while fixing the old one.

`attempts` is incremented here rather than in the review node because it counts
writing passes, and it is the writer's own re-entry that the loop guard bounds.
"""

from __future__ import annotations

from typing import Any

from .. import prompts
from ..integrations.router import ModelRouter
from ..state import EmailDraft, EmailState
from .common import emit_status, merge_trace


def draft_writer_agent(state: EmailState, router: ModelRouter) -> dict[str, Any]:
    attempts = int(state.get("attempts") or 0)
    fix_instructions = state.get("fix_instructions") or ""

    if fix_instructions:
        emit_status(f"Revising the draft (pass {attempts + 1})")
    else:
        emit_status("Writing the draft")

    before = len(router.calls)

    result = router.complete(
        task="draft",
        system=prompts.DRAFT_SYSTEM,
        user=prompts.draft_user(
            parsed=state.get("parsed") or {},
            intent=state.get("intent") or {},
            tone_spec=state.get("tone_spec") or {},
            profile=state.get("profile") or {},
            length_hint=state.get("length_hint") or "medium",
            fix_instructions=fix_instructions,
        ),
        schema=EmailDraft,
    )
    draft: EmailDraft = result.parsed  # type: ignore[assignment]

    # Recount rather than trusting the model's own arithmetic; the UI shows this
    # number next to a length setting, so being off by a third looks like a bug.
    draft.word_count = len(draft.body.split())

    return {
        "draft": draft.model_dump(mode="json"),
        "attempts": attempts + 1,
        # Clear the instructions now they are applied. Leaving them set would make
        # the next review pass look like a revision even when it passed clean.
        "fix_instructions": "",
        "trace": merge_trace(router, before),
    }
