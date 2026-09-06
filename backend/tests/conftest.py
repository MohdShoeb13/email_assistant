"""Shared fixtures.

Every test runs offline. FAKE_LLM is set before any application module is
imported, because config caches settings on first read and a test that imported
early would otherwise capture the developer's real environment — including a
real API key, which would make the suite cost money and depend on the network.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("FAKE_LLM", "1")
os.environ.pop("ANTHROPIC_API_KEY", None)
os.environ.pop("OPENAI_API_KEY", None)

from email_assistant.config import (  # noqa: E402  - must follow the env setup above
    Candidate,
    RetryConfig,
    RoutingConfig,
    TaskRoute,
    reset_caches,
)
from email_assistant.integrations.fake_client import FakeProvider  # noqa: E402
from email_assistant.integrations.router import ModelRouter  # noqa: E402
from email_assistant.memory.profile_store import ProfileStore  # noqa: E402

TASKS = ("parse", "intent", "tone", "draft", "review")


@pytest.fixture(autouse=True)
def _clean_caches():
    reset_caches()
    yield
    reset_caches()


@pytest.fixture
def fast_routing() -> RoutingConfig:
    """A two-candidate route per task with no real backoff.

    The shipped mcp.yaml waits a second between retries, which is right in
    production and would add minutes to this suite. Delays are set to zero so the
    retry logic is still exercised without the wall-clock cost.
    """
    profiles = {
        "quality": {
            task: TaskRoute(
                task=task,
                primary=Candidate("anthropic", "fake-primary"),
                fallbacks=(Candidate("openai", "fake-fallback"),),
            )
            for task in TASKS
        }
    }
    return RoutingConfig(
        active_profile="quality",
        profiles=profiles,
        retry=RetryConfig(max_attempts=2, base_delay_seconds=0.0, max_delay_seconds=0.0),
    )


@pytest.fixture
def store(tmp_path: Path) -> ProfileStore:
    return ProfileStore(tmp_path / "profiles.json")


@pytest.fixture
def router(fast_routing: RoutingConfig) -> ModelRouter:
    """A router wired to fake providers, writing no usage log."""
    fake = FakeProvider()
    return ModelRouter(
        routing=fast_routing,
        providers={"anthropic": fake, "openai": fake},
        profile="quality",
        usage_log_path=None,
    )


def make_router(providers: dict, routing: RoutingConfig, **kwargs) -> ModelRouter:
    return ModelRouter(
        routing=routing, providers=providers, profile="quality", usage_log_path=None, **kwargs
    )
