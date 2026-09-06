"""Model router: candidate walk, fallback triggers, and the usage trace.

These are the tests that matter most in the whole suite. Fallback is the one
behaviour that only shows itself when something has already gone wrong, so it
cannot be checked by using the app normally.
"""

from __future__ import annotations

import json

import pytest

from email_assistant.config import Candidate, RetryConfig, RoutingConfig, TaskRoute
from email_assistant.integrations.base import (
    FatalError,
    NoCandidatesAvailable,
    ProviderUnavailable,
    RetryableError,
)
from email_assistant.integrations.fake_client import FakeProvider
from email_assistant.integrations.router import ModelRouter
from email_assistant.state import ParsedInput

from .conftest import make_router

PROMPT = "Request:\nFollow up with Priya about the pricing deck"


class Unavailable:
    """A configured provider with no credential."""

    name = "unavailable"

    def available(self) -> bool:
        return False

    def complete(self, **kwargs):
        raise AssertionError("an unavailable provider must never be called")


def _parse(router: ModelRouter):
    return router.complete(task="parse", system="s", user=PROMPT, schema=ParsedInput)


def test_primary_serves_when_healthy(fast_routing):
    router = make_router({"anthropic": FakeProvider(), "openai": FakeProvider()}, fast_routing)
    _parse(router)
    assert [c.model for c in router.calls] == ["fake-primary"]
    assert router.calls[0].is_fallback is False


def test_retries_the_same_model_before_moving_on(fast_routing):
    """A transient failure deserves another attempt on the same model first."""
    flaky = FakeProvider(fail_with=RetryableError("blip"), fail_times=1)
    router = make_router({"anthropic": flaky, "openai": FakeProvider()}, fast_routing)
    _parse(router)
    assert [(c.model, c.outcome) for c in router.calls] == [
        ("fake-primary", "error"),
        ("fake-primary", "success"),
    ]


def test_falls_back_across_providers_when_primary_is_exhausted(fast_routing):
    # fast_routing allows 2 attempts, so 2 failures exhaust the primary.
    dead = FakeProvider(fail_with=RetryableError("rate limited"), fail_times=2)
    router = make_router({"anthropic": dead, "openai": FakeProvider()}, fast_routing)
    result = _parse(router)

    assert result.parsed is not None
    assert [c.model for c in router.calls] == [
        "fake-primary",
        "fake-primary",
        "fake-fallback",
    ]
    assert router.calls[-1].is_fallback is True
    assert router.calls[-1].outcome == "success"


def test_failed_attempts_stay_in_the_trace(fast_routing):
    """The failures are the evidence that fallback happened; dropping them
    would leave the UI unable to show anything took place."""
    dead = FakeProvider(fail_with=RetryableError("boom"), fail_times=2)
    router = make_router({"anthropic": dead, "openai": FakeProvider()}, fast_routing)
    _parse(router)

    errors = [c for c in router.calls if c.outcome == "error"]
    assert len(errors) == 2
    assert all(c.error_type == "RetryableError" for c in errors)
    assert all(c.error_message for c in errors)


def test_fatal_error_stops_the_walk(fast_routing):
    """A 400 is our bug. Retrying it against a second model hides it."""
    broken = FakeProvider(fail_with=FatalError("malformed request"), fail_times=99)
    healthy = FakeProvider()
    router = make_router({"anthropic": broken, "openai": healthy}, fast_routing)

    with pytest.raises(FatalError):
        _parse(router)

    assert len(router.calls) == 1
    assert all(c.model != "fake-fallback" for c in router.calls)


def test_provider_without_a_credential_is_skipped_not_tried(fast_routing):
    router = make_router({"anthropic": Unavailable(), "openai": FakeProvider()}, fast_routing)
    _parse(router)
    # Skipping is not a failure, so it must not appear as a failed attempt.
    assert [c.model for c in router.calls] == ["fake-fallback"]
    assert router.calls[0].outcome == "success"


def test_credential_rejected_at_call_time_abandons_that_provider(fast_routing):
    """A bad key should not burn the provider's retry budget."""
    rejected = FakeProvider(fail_with=ProviderUnavailable("401"), fail_times=99)
    router = make_router({"anthropic": rejected, "openai": FakeProvider()}, fast_routing)
    _parse(router)
    assert [c.model for c in router.calls] == ["fake-fallback"]


def test_exhausting_every_candidate_raises_with_a_useful_message(fast_routing):
    dead = FakeProvider(fail_with=RetryableError("down"), fail_times=99)
    router = make_router({"anthropic": dead, "openai": dead}, fast_routing)

    with pytest.raises(NoCandidatesAvailable) as excinfo:
        _parse(router)

    message = str(excinfo.value)
    assert "parse" in message
    assert "fake-primary" in message or "Failed" in message


def test_no_providers_available_at_all(fast_routing):
    router = make_router({"anthropic": Unavailable(), "openai": Unavailable()}, fast_routing)
    with pytest.raises(NoCandidatesAvailable) as excinfo:
        _parse(router)
    assert "no credential" in str(excinfo.value)
    assert router.calls == []


def test_unknown_task_is_rejected_clearly(fast_routing):
    router = make_router({"anthropic": FakeProvider()}, fast_routing)
    with pytest.raises(ValueError, match="no entry for task"):
        router.complete(task="nonexistent", system="s", user="u", schema=ParsedInput)


def test_unknown_profile_is_rejected_clearly(fast_routing):
    router = ModelRouter(
        routing=fast_routing,
        providers={"anthropic": FakeProvider()},
        profile="does-not-exist",
        usage_log_path=None,
    )
    with pytest.raises(ValueError, match="unknown routing profile"):
        router.complete(task="parse", system="s", user="u", schema=ParsedInput)


def test_on_call_hook_fires_per_attempt(fast_routing):
    """The API layer uses this to push a frame the moment an attempt lands,
    rather than waiting for the whole node to finish."""
    seen = []
    flaky = FakeProvider(fail_with=RetryableError("blip"), fail_times=1)
    router = ModelRouter(
        routing=fast_routing,
        providers={"anthropic": flaky, "openai": FakeProvider()},
        profile="quality",
        usage_log_path=None,
        on_call=seen.append,
    )
    _parse(router)
    assert [c.outcome for c in seen] == ["error", "success"]


def test_usage_log_gets_one_line_per_attempt(fast_routing, tmp_path):
    log = tmp_path / "usage.jsonl"
    flaky = FakeProvider(fail_with=RetryableError("blip"), fail_times=1)
    router = ModelRouter(
        routing=fast_routing,
        providers={"anthropic": flaky, "openai": FakeProvider()},
        profile="quality",
        usage_log_path=log,
    )
    _parse(router)

    lines = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert len(lines) == 2
    assert [entry["outcome"] for entry in lines] == ["error", "success"]
    assert all(entry["profile"] == "quality" for entry in lines)
    assert all("ts" in entry for entry in lines)


def test_usage_log_failure_never_breaks_a_request(fast_routing, tmp_path):
    """Telemetry must not be able to fail the draft the user is waiting on."""
    unwritable = tmp_path / "nope.txt" / "usage.jsonl"  # parent is a file-to-be
    (tmp_path / "nope.txt").write_text("blocking", encoding="utf-8")

    router = ModelRouter(
        routing=fast_routing,
        providers={"anthropic": FakeProvider()},
        profile="quality",
        usage_log_path=unwritable,
    )
    assert _parse(router).parsed is not None


def test_provider_status_reports_availability(fast_routing):
    router = make_router({"anthropic": FakeProvider(), "openai": Unavailable()}, fast_routing)
    assert router.provider_status() == {"anthropic": True, "openai": False}


def test_candidates_for_exposes_the_configured_order(fast_routing):
    router = make_router({"anthropic": FakeProvider()}, fast_routing)
    assert [c.model for c in router.candidates_for("draft")] == [
        "fake-primary",
        "fake-fallback",
    ]


def test_single_candidate_route_still_works():
    """A route with no fallbacks must not be treated as misconfigured."""
    routing = RoutingConfig(
        active_profile="quality",
        profiles={
            "quality": {
                "parse": TaskRoute(task="parse", primary=Candidate("anthropic", "fake-only"))
            }
        },
        retry=RetryConfig(max_attempts=1, base_delay_seconds=0.0, max_delay_seconds=0.0),
    )
    router = make_router({"anthropic": FakeProvider()}, routing)
    assert _parse(router).parsed is not None
