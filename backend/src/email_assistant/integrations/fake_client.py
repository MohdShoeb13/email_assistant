"""Offline provider: deterministic, schema-valid responses with no network.

This exists so a fresh clone runs, tests, and demos with no API key and no cost.
It is not a mock in the test-double sense — it is a real provider the router
selects through the ordinary path, which means the offline mode exercises the
same routing, fallback, and trace code that the live mode does. A mock injected
into the router would leave that code untested.

Responses are derived from the actual prompt (recipient names, key points, the
requested tone) rather than being fixed strings, so an offline demo shows the
pipeline genuinely responding to input. Determinism comes from seeding on a hash
of the prompt, so the same request always produces the same draft.
"""

from __future__ import annotations

import hashlib
import random
import re
from typing import Any, Optional, Type

from pydantic import BaseModel

from ..state import (
    EmailDraft,
    Intent,
    IntentResult,
    ParsedInput,
    ReviewIssue,
    ReviewResult,
    Tone,
    ToneSpec,
)
from .base import LLMResult, RetryableError

# Cues that map a request onto an intent, checked in order. First hit wins, which
# is why the more specific phrases come before the generic ones.
_INTENT_CUES: list[tuple[Intent, tuple[str, ...]]] = [
    (Intent.APOLOGY, ("sorry", "apolog", "mistake", "my fault", "went wrong", "missed the")),
    (Intent.THANK_YOU, ("thank", "thanks", "grateful", "appreciate")),
    (Intent.FOLLOW_UP, ("follow up", "follow-up", "following up", "circle back", "checking in", "chase")),
    (Intent.INTERNAL_UPDATE, ("status update", "standup", "sprint", "weekly update", "team update")),
    (Intent.OUTREACH, ("introduce", "introduction", "reach out", "cold", "connect with", "pitch")),
    (Intent.REQUEST, ("can you", "could you", "please send", "need you to", "ask", "request", "sign-off", "approve")),
    (Intent.INFORMATION, ("update", "let them know", "inform", "share", "heads up", "fyi")),
]

_GREETINGS = {
    Tone.FORMAL: "Dear {name},",
    Tone.FRIENDLY: "Hi {name},",
    Tone.CASUAL: "Hey {name},",
    Tone.ASSERTIVE: "Hi {name},",
    Tone.APOLOGETIC: "Hi {name},",
    Tone.CONCISE: "Hi {name},",
}
_CLOSINGS = {
    Tone.FORMAL: "Kind regards,",
    Tone.FRIENDLY: "Thanks,",
    Tone.CASUAL: "Cheers,",
    Tone.ASSERTIVE: "Thanks,",
    Tone.APOLOGETIC: "Thanks for your patience,",
    Tone.CONCISE: "Thanks,",
}
_BANNED = {
    Tone.FORMAL: ["just", "quick", "!", "hey"],
    Tone.FRIENDLY: ["Dear Sir or Madam", "herewith", "per my last email"],
    Tone.CASUAL: ["Kind regards", "Dear", "pursuant to"],
    Tone.ASSERTIVE: ["I was wondering if", "sorry to bother", "maybe", "just checking"],
    Tone.APOLOGETIC: ["sorry for any inconvenience caused", "as per policy"],
    Tone.CONCISE: ["I hope this email finds you well", "just wanted to", "circling back"],
}

# Model ids this fake will answer for. Anything else is rejected the way a real
# provider rejects an unknown model, which is what lets the offline demo show a
# fallback by pointing a route at a bad model id.
#
# Coupled to config/mcp.yaml on purpose: test_config asserts every model named
# there appears here, so adding a model to a routing profile without adding it
# here fails the suite rather than silently breaking offline mode.
KNOWN_MODELS = frozenset(
    {
        "claude-opus-5",
        "claude-sonnet-5",
        "claude-haiku-4-5",
        "gpt-4o",
        "gpt-4o-mini",
    }
)

# Words that look like a name in "email Priya about X" but are not one.
_NOT_NAMES = {
    "the", "and", "about", "regarding", "for", "with", "from", "please", "email",
    "write", "send", "draft", "hi", "hello", "dear", "team", "everyone",
}


class FakeProvider:
    """A provider that answers from the prompt instead of from a model."""

    name = "fake"

    def __init__(self, fail_with: Optional[Exception] = None, fail_times: int = 0) -> None:
        """`fail_with` and `fail_times` let tests and the demo force a fallback.

        Without a way to make a provider fail on demand, the fallback path could
        only be exercised by breaking the config or waiting for a real rate limit.
        """
        self._fail_with = fail_with
        self._fail_times = fail_times
        self._calls = 0

    def available(self) -> bool:
        return True

    def complete(
        self,
        *,
        model: str = "fake-model",
        system: str,
        user: str,
        schema: Optional[Type[BaseModel]] = None,
        max_tokens: int = 16000,
    ) -> LLMResult:
        self._calls += 1
        if self._fail_with is not None and self._calls <= self._fail_times:
            raise self._fail_with

        # Reject a model id no real provider would serve, exactly as a live 404
        # would. Without this the offline mode cannot demonstrate fallback at
        # all: pointing a route at a nonexistent model would silently succeed,
        # which is the one thing a fake provider must not do.
        if model not in KNOWN_MODELS and not model.startswith("fake"):
            raise RetryableError(f"fake: unknown model {model!r}")

        rng = random.Random(hashlib.sha256(user.encode("utf-8")).hexdigest())
        payload: Optional[BaseModel] = None

        if schema is ParsedInput:
            payload = self._parse(user)
        elif schema is IntentResult:
            payload = self._intent(user, rng)
        elif schema is ToneSpec:
            payload = self._tone(user)
        elif schema is EmailDraft:
            payload = self._draft(user)
        elif schema is ReviewResult:
            payload = self._review(user, rng)
        elif schema is not None:
            raise RetryableError(f"fake: no canned response for schema {schema.__name__}")

        text = payload.model_dump_json() if payload is not None else _echo(user)
        return LLMResult(
            text=text,
            parsed=payload,
            provider=self.name,
            model=model,
            # Plausible non-zero counts so the UI's token display has something
            # to render offline; roughly four characters per token.
            input_tokens=max(1, len(system + user) // 4),
            output_tokens=max(1, len(text) // 4),
        )

    # --- canned generators --------------------------------------------------

    def _parse(self, user: str) -> ParsedInput:
        request = _section(user, "Request:") or user
        explicit = _line(user, "Recipient (given explicitly by the user):")
        name = explicit.strip() if explicit else _guess_name(request)
        points = _key_points(request)
        return ParsedInput(
            recipient_name=name,
            recipient_role=None,
            relationship="colleague" if name else "unknown",
            subject_hint=_subject_hint(request),
            key_points=points,
            constraints=_constraints(request),
            length_hint=_length_hint(user),
            language="English",
        )

    def _intent(self, user: str, rng: random.Random) -> IntentResult:
        haystack = user.lower()
        for intent, cues in _INTENT_CUES:
            if any(cue in haystack for cue in cues):
                return IntentResult(
                    intent=intent,
                    confidence=round(rng.uniform(0.78, 0.96), 2),
                    rationale=f"The request contains language characteristic of {intent.value}.",
                )
        return IntentResult(
            intent=Intent.INFORMATION,
            confidence=round(rng.uniform(0.55, 0.7), 2),
            rationale="No dominant cue found; defaulting to sharing information.",
        )

    def _tone(self, user: str) -> ToneSpec:
        tone = _tone_from(user)
        name = _line(user, "Recipient:") or "there"
        name = name.strip() or "there"
        if name.lower().startswith("not named"):
            name = "there"
        return ToneSpec(
            tone=tone,
            voice=f"A {tone.value} voice, matched to a colleague relationship.",
            greeting_style=_GREETINGS[tone].format(name=name),
            closing_style=_CLOSINGS[tone],
            sentence_length="short" if tone in (Tone.CONCISE, Tone.CASUAL, Tone.ASSERTIVE) else "medium",
            use_contractions=tone is not Tone.FORMAL,
            banned_phrases=list(_BANNED[tone]),
            guidance=[
                "State the purpose in the first two sentences.",
                "Cover every key point in the order given.",
                "Do not invent dates, numbers, or attachments.",
                f"Close with exactly: {_CLOSINGS[tone]}",
            ],
        )

    def _draft(self, user: str) -> EmailDraft:
        greeting = (_line(user, "- greeting:") or "Hi there,").strip()
        closing = (_line(user, "- closing:") or "Thanks,").strip()
        subject_area = (_line(user, "- subject area:") or "").strip()
        length = (_line(user, "- length:") or "medium").strip()
        points = _list_section(user, "- key points, in order:")
        constraints = _list_section(user, "- constraints:")
        fixes = _section(user, "REVISION REQUIRED.")

        if not points:
            points = ["the item we discussed"]

        # The first key point usually restates the subject area word for word,
        # since both are extracted from the same sentence. Using it twice reads
        # as a stutter, so the opener only appears when it adds something.
        sentences = [_as_sentence(p) for p in points if p.strip()]
        if subject_area and subject_area != "not stated" and not _overlaps(subject_area, points[0]):
            sentences.insert(0, _as_sentence(f"I wanted to follow up on {subject_area}"))

        seen: set[str] = set()
        deduped = []
        for sentence in sentences:
            key = re.sub(r"[^a-z0-9 ]", "", sentence.lower()).strip()
            if key and key not in seen:
                seen.add(key)
                deduped.append(sentence)

        paragraphs = [" ".join(deduped)]
        if constraints and length != "short":
            paragraphs.append(" ".join(_as_sentence(c) for c in constraints))
        if fixes:
            # Visible proof in the offline demo that the revision loop ran and
            # the writer actually received the reviewer's instructions.
            paragraphs.append("Happy to adjust any of this.")
        elif length != "short":
            paragraphs.append("Let me know if anything needs changing.")

        separator = "\n\n"
        body = separator.join([greeting, *[p for p in paragraphs if p], closing])
        subject_source = subject_area if subject_area and subject_area != "not stated" else points[0]
        return EmailDraft(subject=_title(subject_source)[:80], body=body, word_count=len(body.split()))

    def _review(self, user: str, rng: random.Random) -> ReviewResult:
        body = _section(user, "Draft under review:") or ""
        banned = _list_section(user, "- banned phrases:")
        hits = [p for p in banned if p and p.lower() in body.lower()]

        if hits:
            return ReviewResult(
                passed=False,
                tone_match=round(rng.uniform(0.45, 0.65), 2),
                issues=[
                    ReviewIssue(
                        category="tone",
                        severity="high",
                        detail=f"The draft uses the banned phrase {hit!r}.",
                        suggestion=f"Remove {hit!r} and rephrase the sentence around it.",
                    )
                    for hit in hits[:3]
                ],
                fix_instructions="; ".join(f"Remove the phrase {hit!r}." for hit in hits[:3]),
            )

        return ReviewResult(
            passed=True,
            tone_match=round(rng.uniform(0.82, 0.97), 2),
            issues=[],
            fix_instructions="",
        )


# --- prompt-reading helpers -------------------------------------------------


def _section(text: str, label: str) -> str:
    """Read the multi-line block following `label`, up to the next blank line.

    Only for labels that genuinely introduce a block. Bullet labels inside a
    dense block must use _line instead: the draft prompt has no blank lines
    between its bullets, so _section would swallow the rest of the prompt.
    """
    idx = text.find(label)
    if idx < 0:
        return ""
    rest = text[idx + len(label):]
    chunk = rest.split("\n\n", 1)[0]
    return chunk.strip()


def _line(text: str, label: str) -> str:
    """Read only the remainder of the line `label` appears on."""
    idx = text.find(label)
    if idx < 0:
        return ""
    return text[idx + len(label):].splitlines()[0].strip() if text[idx + len(label):] else ""


def _list_section(text: str, label: str) -> list[str]:
    """Read a Python-repr list rendered into a prompt line."""
    raw = _line(text, label)
    if not raw:
        return []
    items = re.findall(r"'([^']*)'|\"([^\"]*)\"", raw)
    values = [a or b for a, b in items]
    return [v for v in values if v and v not in {"none", "none given", "nothing specified"}]


def _guess_name(text: str) -> Optional[str]:
    for match in re.finditer(r"\b(?:to|with|for)\s+([A-Z][a-z]{1,20})\b", text):
        candidate = match.group(1)
        if candidate.lower() not in _NOT_NAMES:
            return candidate
    for match in re.finditer(r"\b([A-Z][a-z]{2,20})\b", text[1:]):
        candidate = match.group(1)
        if candidate.lower() not in _NOT_NAMES:
            return candidate
    return None


def _subject_hint(text: str) -> Optional[str]:
    match = re.search(r"\babout\s+(.{3,60}?)(?:[.,;]|$)", text, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    match = re.search(r"\b(?:on|regarding|re)\s+(?:the\s+)?(.{3,60}?)(?:[.,;]|$)", text, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return None


def _key_points(text: str) -> list[str]:
    parts = [p.strip(" .") for p in re.split(r"[.;\n]|\band\b(?=\s+[a-z])", text) if p.strip(" .")]
    cleaned = [re.sub(r"^(?:write|send|draft|email|an?)\s+", "", p, flags=re.IGNORECASE) for p in parts]
    return [c for c in cleaned if len(c) > 8][:4] or [text.strip()[:120]]


def _constraints(text: str) -> list[str]:
    out: list[str] = []
    for pattern, template in (
        (r"\bby\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday|tomorrow|today|end of (?:day|week))\b", "Deadline: {0}"),
        (r"\bunder\s+(\d+)\s+words\b", "Maximum {0} words"),
        (r"\bcc\s+([A-Z][a-z]+)\b", "Copy in {0}"),
    ):
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            out.append(template.format(match.group(1)))
    return out


def _length_hint(text: str) -> str:
    lowered = text.lower()
    if "requested length: short" in lowered or "brief" in lowered:
        return "short"
    if "requested length: long" in lowered or "detailed" in lowered:
        return "long"
    return "medium"


def _tone_from(text: str) -> Tone:
    match = re.search(r"Tone requested:\s*([a-z-]+)", text, re.IGNORECASE)
    if match:
        try:
            return Tone(match.group(1).strip().lower())
        except ValueError:
            pass
    return Tone.FRIENDLY


def _as_sentence(point: str) -> str:
    point = point.strip()
    if not point:
        return ""
    point = point[0].upper() + point[1:]
    return point if point.endswith((".", "!", "?")) else point + "."


def _title(text: str) -> str:
    words = re.sub(r"\s+", " ", text).strip().split()
    if not words:
        return "Quick note"
    title = " ".join(words[:8]).rstrip(".,;")
    return title[0].upper() + title[1:]


def _echo(user: str) -> str:
    return f"[offline] {user.strip()[:200]}"


def _overlaps(a: str, b: str) -> bool:
    """True when two extracted fragments say substantially the same thing."""
    tokens_a = {w for w in re.findall(r"[a-z0-9]+", a.lower()) if len(w) > 3}
    tokens_b = {w for w in re.findall(r"[a-z0-9]+", b.lower()) if len(w) > 3}
    if not tokens_a or not tokens_b:
        return False
    return len(tokens_a & tokens_b) / len(tokens_a) >= 0.6
