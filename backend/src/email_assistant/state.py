"""Graph state and every structured payload the agents exchange.

Each agent returns a Pydantic model rather than free text. That is what lets the
router treat a schema-validation failure the same as a network failure: in both
cases we did not get a usable answer, so the next candidate model deserves a turn.
With free-text parsing, "the model answered badly" and "the model answered in a
shape we cannot read" would be indistinguishable, and neither could be retried.
"""

from __future__ import annotations

import operator
from enum import Enum
from typing import Annotated, Any, Literal, Optional, TypedDict

from pydantic import BaseModel, Field

# Two revisions is the point where the review agent has either fixed the draft or
# is deadlocked with the writer. Past that, more attempts cost tokens and change
# nothing, so the graph degrades to "needs_review" instead of looping.
MAX_REVISIONS = 2


class Intent(str, Enum):
    """What the email is for. Drives structure, not wording."""

    OUTREACH = "outreach"
    FOLLOW_UP = "follow-up"
    APOLOGY = "apology"
    INFORMATION = "information"
    INTERNAL_UPDATE = "internal-update"
    REQUEST = "request"
    THANK_YOU = "thank-you"


class Tone(str, Enum):
    """Named tones. Each one is backed by a file in data/tone_samples/."""

    FORMAL = "formal"
    FRIENDLY = "friendly"
    CASUAL = "casual"
    ASSERTIVE = "assertive"
    APOLOGETIC = "apologetic"
    CONCISE = "concise"


# --- Agent outputs ----------------------------------------------------------


class ParsedInput(BaseModel):
    """Input Parsing Agent: turns a loose prompt into named fields."""

    recipient_name: Optional[str] = Field(None, description="Recipient's name if stated")
    recipient_role: Optional[str] = Field(None, description="Their role or relationship to the sender")
    relationship: Literal[
        "colleague", "manager", "report", "client", "vendor", "stranger", "unknown"
    ] = "unknown"
    subject_hint: Optional[str] = Field(None, description="What the email is about, in a few words")
    key_points: list[str] = Field(default_factory=list, description="Points the email must make, in order")
    constraints: list[str] = Field(
        default_factory=list, description="Explicit constraints, such as a deadline or a word limit"
    )
    length_hint: Literal["short", "medium", "long"] = "medium"
    language: str = Field("English", description="Language to write the email in")


class IntentResult(BaseModel):
    """Intent Detection Agent: classifies the purpose of the email."""

    intent: Intent
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str = Field(description="One sentence on why this intent and not another")


class ToneSpec(BaseModel):
    """Tone Stylist Agent: a concrete style contract handed to the writer.

    Deliberately prescriptive. "Write in a friendly tone" is not reproducible
    across models or runs; a named greeting form, a sentence-length target and a
    banned-phrase list are, and the review agent can check them.
    """

    tone: Tone
    voice: str = Field(description="One line describing the voice")
    greeting_style: str = Field(description="Exact greeting form to use")
    closing_style: str = Field(description="Exact closing form to use")
    sentence_length: Literal["short", "medium", "long"] = "medium"
    use_contractions: bool = True
    banned_phrases: list[str] = Field(default_factory=list)
    guidance: list[str] = Field(default_factory=list, description="Concrete do and don't rules")


class EmailDraft(BaseModel):
    """Draft Writer Agent: the deliverable."""

    subject: str
    body: str = Field(description="Body including greeting and closing, excluding the signature block")
    word_count: int = Field(default=0, ge=0)


class ReviewIssue(BaseModel):
    """One specific, actionable problem with a draft."""

    category: Literal["grammar", "tone", "coherence", "factual", "structure"]
    severity: Literal["low", "medium", "high"]
    detail: str
    suggestion: str


class ReviewResult(BaseModel):
    """Review and Validator Agent: the quality gate that can send a draft back."""

    passed: bool
    tone_match: float = Field(ge=0.0, le=1.0, description="How well the draft matches the ToneSpec")
    issues: list[ReviewIssue] = Field(default_factory=list)
    fix_instructions: str = Field("", description="What the writer should change; empty when passed")


# --- Observability ----------------------------------------------------------


class ModelCall(BaseModel):
    """One attempt against one model, recorded whether or not it succeeded.

    Failed attempts are the interesting records: they are the only evidence that
    fallback happened at all, so they stay in the trace rather than being dropped.
    """

    task: str
    provider: str
    model: str
    attempt: int
    outcome: Literal["success", "error"]
    latency_ms: int
    input_tokens: int = 0
    output_tokens: int = 0
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    is_fallback: bool = False


# --- Graph state ------------------------------------------------------------


class EmailState(TypedDict, total=False):
    """State threaded through the LangGraph pipeline.

    `trace` and `errors` accumulate with operator.add so that a node running twice
    (the revision loop) appends rather than overwrites. Everything else is a
    last-write-wins slot.
    """

    # Request
    session_id: str
    user_id: str
    raw_prompt: str
    requested_tone: Optional[str]
    requested_intent: Optional[str]
    recipient: Optional[str]
    length_hint: str
    routing_profile: str

    # Agent outputs, held as plain dicts so the state stays JSON-serializable
    # for the checkpointer and the SSE layer.
    parsed: Optional[dict[str, Any]]
    intent: Optional[dict[str, Any]]
    tone_spec: Optional[dict[str, Any]]
    profile: dict[str, Any]
    draft: Optional[dict[str, Any]]
    review: Optional[dict[str, Any]]

    # Control
    attempts: int
    fix_instructions: str
    draft_id: str
    status: Literal["running", "complete", "needs_review", "failed"]

    # Observability
    trace: Annotated[list[dict[str, Any]], operator.add]
    errors: Annotated[list[str], operator.add]


def new_state(
    *,
    raw_prompt: str,
    user_id: str = "default",
    session_id: str = "",
    requested_tone: Optional[str] = None,
    requested_intent: Optional[str] = None,
    recipient: Optional[str] = None,
    length_hint: str = "medium",
    routing_profile: str = "quality",
) -> EmailState:
    """Build a fully populated initial state.

    Every accumulator starts as a real empty list. A LangGraph reducer needs a
    value to add to, and a missing key here surfaces much later as a confusing
    error inside whichever node happened to write first.
    """
    return EmailState(
        session_id=session_id,
        user_id=user_id,
        raw_prompt=raw_prompt,
        requested_tone=requested_tone,
        requested_intent=requested_intent,
        recipient=recipient,
        length_hint=length_hint,
        routing_profile=routing_profile,
        parsed=None,
        intent=None,
        tone_spec=None,
        profile={},
        draft=None,
        review=None,
        attempts=0,
        fix_instructions="",
        draft_id="",
        status="running",
        trace=[],
        errors=[],
    )
