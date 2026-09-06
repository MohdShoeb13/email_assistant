"""HTTP API: the SSE event sequence and the profile/edit endpoints."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from email_assistant.api.app import app
from email_assistant.workflow.langgraph_flow import AGENT_SEQUENCE

PROMPT = "Follow up with Priya about the Q3 pricing deck and ask for sign-off by Friday"


@pytest.fixture
def client(tmp_path, monkeypatch):
    """A client whose profile store and usage log are redirected to tmp_path.

    Without this the suite would write into the repository's data directory and
    tests would see each other's draft history.
    """
    from email_assistant.api import app as app_module
    from email_assistant.integrations import router as router_module
    from email_assistant.memory.profile_store import ProfileStore

    store = ProfileStore(tmp_path / "profiles.json")
    monkeypatch.setattr(app_module, "_store", lambda: store)
    monkeypatch.setattr(router_module, "USAGE_LOG_PATH", tmp_path / "usage.jsonl")
    with TestClient(app) as test_client:
        yield test_client


def parse_sse(text: str) -> list[tuple[str, dict]]:
    """Read an SSE body into (event, data) pairs."""
    events: list[tuple[str, dict]] = []
    name = None
    for block in text.replace("\r\n", "\n").split("\n\n"):
        payload_lines = []
        for line in block.split("\n"):
            if line.startswith("event:"):
                name = line[len("event:"):].strip()
            elif line.startswith("data:"):
                payload_lines.append(line[len("data:"):].strip())
        if name and payload_lines:
            events.append((name, json.loads("".join(payload_lines))))
            name = None
    return events


def run(client, **overrides) -> list[tuple[str, dict]]:
    body = {"prompt": PROMPT, "tone": "friendly", "user_id": "alice"}
    body.update(overrides)
    response = client.post("/api/generate", json=body)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    return parse_sse(response.text)


# --- health and config ------------------------------------------------------


def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}


def test_config_describes_the_ui_controls(client):
    body = client.get("/api/config").json()
    assert body["offline"] is True  # the suite runs with no keys
    assert set(body["routing_profiles"]) == {"cost", "quality"}
    assert "friendly" in body["tones"]
    assert body["intents"][0] == "auto"
    assert [agent["id"] for agent in body["agents"]] == AGENT_SEQUENCE
    assert body["max_revisions"] >= 1


def test_config_reports_provider_availability(client):
    providers = {p["name"]: p["available"] for p in client.get("/api/config").json()["providers"]}
    assert "anthropic" in providers and "openai" in providers


# --- generation stream ------------------------------------------------------


def test_generate_streams_the_expected_event_sequence(client):
    events = run(client)
    names = [name for name, _ in events]

    assert names[0] == "run_start"
    assert names[-1] == "done"
    assert "draft" in names
    assert "model_call" in names


def test_every_agent_reports_start_and_done(client):
    events = run(client)
    done_nodes = [payload["node"] for name, payload in events if name == "agent_done"]
    started = {payload["node"] for name, payload in events if name == "agent_start"}

    assert done_nodes == AGENT_SEQUENCE
    assert started == set(AGENT_SEQUENCE)


def test_agent_done_carries_that_agent_output(client):
    events = run(client)
    outputs = {p["node"]: p["output"] for n, p in events if n == "agent_done"}
    assert outputs["input_parser"]["key_points"]
    assert outputs["intent_detection"]["intent"]
    assert outputs["tone_stylist"]["greeting_style"]
    assert outputs["draft_writer"]["subject"]


def test_run_start_describes_the_pipeline(client):
    events = run(client)
    _, payload = events[0]
    assert [a["id"] for a in payload["agents"]] == AGENT_SEQUENCE
    assert payload["session_id"]
    assert payload["routing_profile"] in {"quality", "cost"}


def test_model_calls_are_reported_with_provider_and_model(client):
    events = run(client)
    calls = [payload for name, payload in events if name == "model_call"]
    assert len(calls) == 5  # parse, intent, tone, draft, review
    for call in calls:
        assert call["provider"] and call["model"] and call["task"]
        assert call["outcome"] in {"success", "error"}


def test_draft_is_pushed_before_the_run_ends(client):
    """The user should be able to read the draft while review is still running."""
    names = [name for name, _ in run(client)]
    assert names.index("draft") < names.index("done")


def test_done_carries_the_full_result(client):
    events = run(client)
    _, done = events[-1]
    assert done["status"] == "complete"
    assert done["draft"]["subject"] and done["draft"]["body"]
    assert done["review"]["passed"] is True
    assert len(done["trace"]) == 5
    assert done["draft_id"]


def test_explicit_intent_is_honoured(client):
    events = run(client, intent="apology")
    _, done = events[-1]
    assert done["intent"]["intent"] == "apology"


def test_cost_profile_is_selectable(client):
    events = run(client, routing_profile="cost")
    _, start = events[0]
    assert start["routing_profile"] == "cost"
    calls = [p for n, p in events if n == "model_call"]
    # The cost profile downgrades classification but not the draft.
    by_task = {c["task"]: c["model"] for c in calls}
    assert by_task["parse"] != by_task["draft"]


def test_a_prompt_too_short_ends_as_failed_not_a_500(client):
    events = run(client, prompt="hi")  # under MIN_PROMPT_CHARS
    _, done = events[-1]
    assert done["status"] == "failed"
    assert done["errors"]


def test_unknown_routing_profile_is_a_400(client):
    response = client.post(
        "/api/generate", json={"prompt": PROMPT, "routing_profile": "nonexistent"}
    )
    assert response.status_code == 400
    assert "unknown routing profile" in response.json()["detail"]


def test_empty_prompt_is_rejected(client):
    assert client.post("/api/generate", json={"prompt": "   "}).status_code == 400
    assert client.post("/api/generate", json={"prompt": ""}).status_code == 422


# --- profiles ---------------------------------------------------------------


def test_profile_round_trip(client):
    client.put("/api/profile/alice", json={"name": "Alice", "company": "Acme"})
    profile = client.get("/api/profile/alice").json()["profile"]
    assert profile["name"] == "Alice"
    assert profile["company"] == "Acme"


def test_partial_update_does_not_blank_other_fields(client):
    client.put("/api/profile/alice", json={"name": "Alice", "company": "Acme"})
    client.put("/api/profile/alice", json={"company": "Globex"})
    profile = client.get("/api/profile/alice").json()["profile"]
    assert profile["name"] == "Alice"
    assert profile["company"] == "Globex"


def test_unknown_user_returns_a_blank_profile(client):
    profile = client.get("/api/profile/ghost").json()["profile"]
    assert profile["user_id"] == "ghost"
    assert profile["style_evidence_count"] == 0


# --- edits feed back into personalization -----------------------------------


def test_saving_an_edit_records_style_evidence(client):
    response = client.post(
        "/api/drafts/d1/edits",
        json={
            "user_id": "alice",
            "original_body": "Hi Priya,\n\nPlease find attached the deck.",
            "edited_body": "Hey Priya,\n\nDeck's attached.",
        },
    )
    body = response.json()
    assert body["saved"] is True
    assert body["evidence_count"] == 1
    assert client.get("/api/profile/alice").json()["profile"]["style_evidence_count"] == 1


def test_an_unchanged_edit_is_not_stored(client):
    """Pressing save without changing anything teaches the stylist nothing."""
    response = client.post(
        "/api/drafts/d1/edits",
        json={"user_id": "alice", "original_body": "same text", "edited_body": "same text"},
    )
    assert response.json()["saved"] is False
    assert client.get("/api/profile/alice").json()["profile"]["style_evidence_count"] == 0


def test_generation_records_draft_history(client):
    run(client)
    assert client.get("/api/profile/alice").json()["profile"]["draft_history"]
