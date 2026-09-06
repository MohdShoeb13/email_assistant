"""Input Parsing Agent: validates the prompt and normalizes it into named fields.

First node in the graph, and the only one that rejects input. Everything
downstream assumes a ParsedInput exists, so a request too empty to parse is
stopped here rather than producing a confidently empty email three agents later.
"""

from __future__ import annotations

from typing import Any

from .. import prompts
from ..integrations.router import ModelRouter
from ..state import EmailState, ParsedInput
from .common import emit_status, first_nonempty, merge_trace

# Below this, there is nothing to write an email about. The number is a floor on
# meaningfulness, not on cost: "hi" parses fine and yields an empty draft.
MIN_PROMPT_CHARS = 8


def input_parser_agent(state: EmailState, router: ModelRouter) -> dict[str, Any]:
    prompt = (state.get("raw_prompt") or "").strip()
    if len(prompt) < MIN_PROMPT_CHARS:
        return {
            "status": "failed",
            "errors": [
                f"The request is too short to write an email from "
                f"(need at least {MIN_PROMPT_CHARS} characters). "
                f"Say who it is for and what it should cover."
            ],
        }

    emit_status("Reading the request")
    before = len(router.calls)

    result = router.complete(
        task="parse",
        system=prompts.INPUT_PARSER_SYSTEM,
        user=prompts.input_parser_user(
            raw_prompt=prompt,
            recipient=state.get("recipient"),
            length_hint=state.get("length_hint") or "medium",
        ),
        schema=ParsedInput,
    )
    parsed: ParsedInput = result.parsed  # type: ignore[assignment]

    # An explicitly typed recipient beats whatever the model inferred from prose.
    # The user filling in that field is a direct statement; the model reading a
    # capitalized word out of a sentence is a guess.
    explicit = first_nonempty(state.get("recipient"))
    if explicit:
        parsed.recipient_name = explicit

    # The UI's length control is a request, not a hint to be re-litigated.
    requested_length = state.get("length_hint")
    if requested_length in ("short", "medium", "long"):
        parsed.length_hint = requested_length

    return {
        "parsed": parsed.model_dump(mode="json"),
        "trace": merge_trace(router, before),
    }
