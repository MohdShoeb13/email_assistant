"""The compiled graph: happy path, the revision loop, and its bound."""

from __future__ import annotations

import pytest

from email_assistant.integrations.base import RetryableError
from email_assistant.integrations.fake_client import FakeProvider
from email_assistant.state import MAX_REVISIONS, ReviewResult, new_state
from email_assistant.workflow.langgraph_flow import (
    AGENT_SEQUENCE,
    build_graph,
    route_after_review,
    run_graph,
    stream_graph,
)

from .conftest import make_router

PROMPT = "Follow up with Priya about the Q3 pricing deck and ask for sign-off by Friday"


class AlwaysRejects(FakeProvider):
    """A reviewer that never accepts, to force the loop to its bound."""

    def complete(self, **kwargs):
        result = super().complete(**kwargs)
        if isinstance(result.parsed, ReviewResult):
            result.parsed.passed = False
            result.parsed.tone_match = 0.3
            result.parsed.fix_instructions = "Tighten the opening."
        return result


def _graph(router, store):
    return build_graph(router, store)


def _state(**overrides):
    state = new_state(raw_prompt=PROMPT, requested_tone="friendly", session_id="t1")
    state.update(overrides)
    return state


# --- routing decision -------------------------------------------------------


def test_passing_review_goes_to_the_router():
    assert route_after_review({"review": {"passed": True}, "attempts": 1}) == "router"


def test_failing_review_goes_back_to_the_writer():
    assert route_after_review({"review": {"passed": False}, "attempts": 1}) == "draft_writer"


def test_the_loop_is_bounded():
    """Without this bound a stubborn reviewer spins until LangGraph's recursion
    limit fires, which surfaces as a framework error instead of a draft."""
    state = {"review": {"passed": False}, "attempts": MAX_REVISIONS + 1}
    assert route_after_review(state) == "router"


# --- end to end -------------------------------------------------------------


def test_happy_path_produces_a_complete_draft(router, store):
    final = run_graph(_graph(router, store), _state(), thread_id="t1")
    assert final["status"] == "complete"
    assert final["draft"]["subject"]
    assert final["draft"]["body"]
    assert final["attempts"] == 1
    assert final["review"]["passed"] is True


def test_every_agent_output_is_populated(router, store):
    final = run_graph(_graph(router, store), _state(), thread_id="t1")
    for key in ("parsed", "intent", "tone_spec", "profile", "draft", "review"):
        assert final[key], f"{key} was not populated"


def test_the_trace_records_every_model_call(router, store):
    final = run_graph(_graph(router, store), _state(), thread_id="t1")
    # parse, intent, tone, draft, review - personalization and router make none.
    assert len(final["trace"]) == 5
    assert {entry["task"] for entry in final["trace"]} == {
        "parse",
        "intent",
        "tone",
        "draft",
        "review",
    }


def test_the_draft_is_saved_to_history(router, store):
    run_graph(_graph(router, store), _state(user_id="alice"), thread_id="t1")
    assert store.get("alice")["draft_history"]


def test_a_rejecting_reviewer_stops_at_the_bound(fast_routing, store):
    """The run must end with the best draft flagged, not with an exception."""
    router = make_router({"anthropic": AlwaysRejects(), "openai": AlwaysRejects()}, fast_routing)
    final = run_graph(_graph(router, store), _state(), thread_id="t1")

    assert final["status"] == "needs_review"
    assert final["draft"]["body"]  # a usable draft is still handed back
    assert final["attempts"] == MAX_REVISIONS + 1
    assert final["review"]["passed"] is False


def test_the_writer_actually_reruns_on_rejection(fast_routing, store):
    router = make_router({"anthropic": AlwaysRejects(), "openai": AlwaysRejects()}, fast_routing)
    final = run_graph(_graph(router, store), _state(), thread_id="t1")
    draft_calls = [entry for entry in final["trace"] if entry["task"] == "draft"]
    assert len(draft_calls) == MAX_REVISIONS + 1


def test_a_prompt_too_short_fails_cleanly(router, store):
    final = run_graph(_graph(router, store), _state(raw_prompt="hi"), thread_id="t1")
    assert final["status"] == "failed"
    assert final["errors"]


def test_total_model_failure_ends_the_run_without_a_traceback(fast_routing, store):
    """By this point the router has tried every candidate. Raising would abort
    the stream and leave the UI on a spinner."""
    dead = FakeProvider(fail_with=RetryableError("everything is down"), fail_times=99)
    router = make_router({"anthropic": dead, "openai": dead}, fast_routing)

    final = run_graph(_graph(router, store), _state(), thread_id="t1")
    assert final["status"] == "failed"
    assert any("could not complete" in error for error in final["errors"])


# --- streaming --------------------------------------------------------------


def test_streaming_emits_every_node_in_order(router, store):
    events = list(stream_graph(_graph(router, store), _state(), thread_id="t1"))
    nodes = [event["node"] for event in events if event["kind"] == "node"]
    assert nodes == AGENT_SEQUENCE


def test_streaming_emits_status_lines(router, store):
    events = list(stream_graph(_graph(router, store), _state(), thread_id="t1"))
    statuses = [event["message"] for event in events if event["kind"] == "status"]
    assert statuses
    assert all(isinstance(message, str) and message for message in statuses)


def test_streaming_carries_the_node_update_payloads(router, store):
    events = list(stream_graph(_graph(router, store), _state(), thread_id="t1"))
    by_node = {event["node"]: event["update"] for event in events if event["kind"] == "node"}
    assert "parsed" in by_node["input_parser"]
    assert "draft" in by_node["draft_writer"]
    assert "review" in by_node["review"]
    assert by_node["router"]["status"] == "complete"


def test_the_agent_sequence_matches_the_graph(router, store):
    """AGENT_SEQUENCE drives the UI's pipeline rail, so it must not drift from
    the nodes the graph actually runs."""
    events = list(stream_graph(_graph(router, store), _state(), thread_id="t1"))
    assert set(event["node"] for event in events if event["kind"] == "node") == set(AGENT_SEQUENCE)


# --- determinism ------------------------------------------------------------


def test_the_offline_provider_is_deterministic(router, store, fast_routing):
    """Same request, same draft. A demo that changes every run is not a demo."""
    first = run_graph(_graph(router, store), _state(), thread_id="a")
    second_router = make_router(
        {"anthropic": FakeProvider(), "openai": FakeProvider()}, fast_routing
    )
    second = run_graph(_graph(second_router, store), _state(), thread_id="b")
    assert first["draft"]["body"] == second["draft"]["body"]


@pytest.mark.parametrize("tone", ["formal", "friendly", "casual", "assertive", "concise"])
def test_each_tone_produces_a_distinct_contract(router, store, tone):
    final = run_graph(_graph(router, store), _state(requested_tone=tone), thread_id=tone)
    assert final["tone_spec"]["tone"] == tone
    assert final["draft"]["body"].endswith(final["tone_spec"]["closing_style"])
