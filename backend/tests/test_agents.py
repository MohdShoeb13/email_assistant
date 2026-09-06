"""Each agent in isolation, against fake providers."""

from __future__ import annotations

from email_assistant.agents.draft_writer_agent import draft_writer_agent
from email_assistant.agents.input_parser_agent import MIN_PROMPT_CHARS, input_parser_agent
from email_assistant.agents.intent_detection_agent import intent_detection_agent
from email_assistant.agents.personalization_agent import personalization_agent
from email_assistant.agents.review_agent import review_agent
from email_assistant.agents.router_agent import router_agent
from email_assistant.agents.tone_stylist_agent import tone_stylist_agent
from email_assistant.state import (
    MAX_REVISIONS,
    EmailDraft,
    IntentResult,
    ParsedInput,
    ReviewResult,
    ToneSpec,
    new_state,
)

PROMPT = "Follow up with Priya about the Q3 pricing deck and ask for sign-off by Friday"


def _state(**overrides):
    state = new_state(raw_prompt=PROMPT, requested_tone="friendly", session_id="t1")
    state.update(overrides)
    return state


# --- input parser -----------------------------------------------------------


def test_input_parser_returns_a_valid_schema(router):
    update = input_parser_agent(_state(), router)
    parsed = ParsedInput.model_validate(update["parsed"])
    assert parsed.key_points
    assert update["trace"]


def test_input_parser_rejects_a_prompt_too_short_to_use(router):
    """Stopping here beats producing a confidently empty email three agents on."""
    update = input_parser_agent(_state(raw_prompt="hi"), router)
    assert update["status"] == "failed"
    assert update["errors"]
    assert str(MIN_PROMPT_CHARS) in update["errors"][0]
    assert router.calls == []  # no model was called


def test_input_parser_rejects_whitespace_only(router):
    assert input_parser_agent(_state(raw_prompt="        "), router)["status"] == "failed"


def test_explicit_recipient_overrides_the_inferred_one(router):
    """The user typing a name is a statement; the model reading one is a guess."""
    update = input_parser_agent(_state(recipient="Dr Raman"), router)
    assert update["parsed"]["recipient_name"] == "Dr Raman"


def test_requested_length_is_not_relitigated(router):
    update = input_parser_agent(_state(length_hint="short"), router)
    assert update["parsed"]["length_hint"] == "short"


# --- intent detection -------------------------------------------------------


def test_intent_detection_returns_a_valid_schema(router):
    state = _state(parsed=input_parser_agent(_state(), router)["parsed"])
    update = intent_detection_agent(state, router)
    IntentResult.model_validate(update["intent"])


def test_explicit_intent_skips_the_model_call(router):
    before = len(router.calls)
    update = intent_detection_agent(_state(requested_intent="apology"), router)
    assert update["intent"]["intent"] == "apology"
    assert update["intent"]["confidence"] == 1.0
    assert len(router.calls) == before  # nothing was asked


def test_auto_intent_still_calls_the_model(router):
    intent_detection_agent(_state(requested_intent="auto", parsed={}), router)
    assert router.calls


def test_invalid_requested_intent_falls_through_to_detection(router):
    update = intent_detection_agent(_state(requested_intent="nonsense", parsed={}), router)
    assert update["intent"]["confidence"] < 1.0


# --- personalization --------------------------------------------------------


def test_personalization_loads_the_profile_without_a_model_call(router, store):
    store.save("alice", {"name": "Alice", "company": "Acme"})
    before = len(router.calls)
    update = personalization_agent(_state(user_id="alice"), store=store)
    assert update["profile"]["name"] == "Alice"
    assert len(router.calls) == before


def test_personalization_attaches_style_evidence(store):
    store.record_edit("alice", draft_id="d1", original_body="formal text", edited_body="casual text")
    update = personalization_agent(_state(user_id="alice"), store=store)
    assert update["profile"]["style_evidence"][0]["edited"] == "casual text"


def test_personalization_handles_an_unknown_user(store):
    update = personalization_agent(_state(user_id="ghost"), store=store)
    assert update["profile"]["user_id"] == "ghost"
    assert update["profile"]["style_evidence"] == []


# --- tone stylist -----------------------------------------------------------


def test_tone_stylist_returns_a_valid_contract(router):
    parsed = input_parser_agent(_state(), router)["parsed"]
    update = tone_stylist_agent(_state(parsed=parsed, intent={"intent": "follow-up"}), router)
    spec = ToneSpec.model_validate(update["tone_spec"])
    assert spec.tone.value == "friendly"
    assert spec.greeting_style and spec.closing_style


def test_tone_falls_back_to_the_profile_default(router):
    state = _state(requested_tone=None, profile={"default_tone": "formal"}, parsed={}, intent={})
    update = tone_stylist_agent(state, router)
    assert update["tone_spec"]["tone"] == "formal"


def test_tone_falls_back_to_friendly_with_nothing_set(router):
    state = _state(requested_tone=None, profile={}, parsed={}, intent={})
    assert tone_stylist_agent(state, router)["tone_spec"]["tone"] == "friendly"


# --- draft writer -----------------------------------------------------------


def _through_tone(router, **overrides):
    state = _state(**overrides)
    state.update(input_parser_agent(state, router))
    state.update(intent_detection_agent(state, router))
    state.update({"profile": {}})
    state.update(tone_stylist_agent(state, router))
    return state


def test_draft_writer_returns_a_valid_draft(router):
    state = _through_tone(router)
    update = draft_writer_agent(state, router)
    draft = EmailDraft.model_validate(update["draft"])
    assert draft.subject and draft.body
    assert update["attempts"] == 1


def test_draft_writer_recounts_words_itself(router):
    """The UI shows this next to a length control, so a wrong count reads as a bug."""
    update = draft_writer_agent(_through_tone(router), router)
    assert update["draft"]["word_count"] == len(update["draft"]["body"].split())


def test_draft_writer_clears_fix_instructions_after_applying_them(router):
    state = _through_tone(router)
    state["fix_instructions"] = "Remove the phrase 'per my last email'."
    update = draft_writer_agent(state, router)
    assert update["fix_instructions"] == ""


def test_draft_writer_increments_attempts_across_revisions(router):
    state = _through_tone(router)
    state.update(draft_writer_agent(state, router))
    state["fix_instructions"] = "Shorten it."
    assert draft_writer_agent(state, router)["attempts"] == 2


def test_draft_uses_the_greeting_from_the_contract(router):
    state = _through_tone(router)
    update = draft_writer_agent(state, router)
    assert update["draft"]["body"].startswith(state["tone_spec"]["greeting_style"])


# --- review -----------------------------------------------------------------


def test_review_returns_a_valid_verdict(router):
    state = _through_tone(router)
    state.update(draft_writer_agent(state, router))
    update = review_agent(state, router)
    ReviewResult.model_validate(update["review"])


def test_review_with_no_draft_fails_without_calling_a_model(router):
    before = len(router.calls)
    update = review_agent(_state(draft=None), router)
    assert update["review"]["passed"] is False
    assert update["errors"]
    assert len(router.calls) == before


def test_a_passing_review_carries_no_fix_instructions(router):
    """A pass with instructions attached would re-run the writer on an accepted draft."""
    state = _through_tone(router)
    state.update(draft_writer_agent(state, router))
    update = review_agent(state, router)
    if update["review"]["passed"]:
        assert update["review"]["fix_instructions"] == ""
        assert update["fix_instructions"] == ""


# --- router agent -----------------------------------------------------------


def test_router_marks_a_passing_run_complete(store):
    state = _state(draft={"subject": "s", "body": "b"}, review={"passed": True}, attempts=1)
    update = router_agent(state, store=store)
    assert update["status"] == "complete"
    assert update["draft_id"]


def test_router_flags_an_unresolved_draft_rather_than_dropping_it(store):
    """A draft with known issues is more use than none."""
    state = _state(
        draft={"subject": "s", "body": "b"},
        review={"passed": False},
        attempts=MAX_REVISIONS + 1,
    )
    assert router_agent(state, store=store)["status"] == "needs_review"


def test_router_fails_when_there_is_no_draft(store):
    state = _state(draft=None, review={"passed": False})
    assert router_agent(state, store=store)["status"] == "failed"


def test_router_persists_the_draft_to_history(store):
    state = _state(
        user_id="alice",
        draft={"subject": "Q3 deck", "body": "Hi Priya,"},
        review={"passed": True},
        tone_spec={"tone": "friendly"},
        intent={"intent": "follow-up"},
        attempts=1,
    )
    router_agent(state, store=store)
    history = store.get("alice")["draft_history"]
    assert history[-1]["subject"] == "Q3 deck"
    assert history[-1]["tone"] == "friendly"


def test_router_makes_no_model_call(router, store):
    before = len(router.calls)
    router_agent(
        _state(draft={"subject": "s", "body": "b"}, review={"passed": True}), store=store
    )
    assert len(router.calls) == before
