"""Review and Validator Agent: the quality gate that can send a draft back.

Checks the draft against the style contract and, more importantly, against the
facts the user actually supplied. Invented specifics — a date, a number, an
attachment nobody mentioned — are the failure mode that matters most in a tool
that drafts on your behalf, because they are the ones a reader will act on.

The node reports a verdict; the graph's conditional edge decides what to do with
it. Keeping the routing decision out of the agent is what lets the loop bound be
changed without touching review logic.
"""

from __future__ import annotations

from typing import Any

from .. import prompts
from ..integrations.router import ModelRouter
from ..state import EmailState, ReviewResult
from .common import emit_status, merge_trace


def review_agent(state: EmailState, router: ModelRouter) -> dict[str, Any]:
    draft = state.get("draft") or {}
    if not draft:
        return {
            "review": ReviewResult(
                passed=False,
                tone_match=0.0,
                issues=[],
                fix_instructions="No draft was produced.",
            ).model_dump(mode="json"),
            "errors": ["Review ran with no draft to check."],
        }

    emit_status("Checking tone, grammar, and invented facts")
    before = len(router.calls)

    result = router.complete(
        task="review",
        system=prompts.REVIEW_SYSTEM,
        user=prompts.review_user(
            draft=draft,
            tone_spec=state.get("tone_spec") or {},
            parsed=state.get("parsed") or {},
            raw_prompt=state.get("raw_prompt") or "",
        ),
        schema=ReviewResult,
    )
    review: ReviewResult = result.parsed  # type: ignore[assignment]

    # A pass with instructions attached is contradictory. Trust the verdict and
    # drop the instructions, so the writer is never re-run on an accepted draft.
    if review.passed:
        review.fix_instructions = ""

    return {
        "review": review.model_dump(mode="json"),
        "fix_instructions": review.fix_instructions,
        "trace": merge_trace(router, before),
    }
