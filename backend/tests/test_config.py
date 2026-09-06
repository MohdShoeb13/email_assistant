"""Routing config parsing, and the shipped mcp.yaml itself."""

from __future__ import annotations

import pytest

from email_assistant.config import (
    MCP_CONFIG_PATH,
    TONE_SAMPLES_DIR,
    load_routing_config,
    load_tone_sample,
)
from email_assistant.state import Tone

TASKS = {"parse", "intent", "tone", "draft", "review"}


def test_shipped_config_parses():
    config = load_routing_config()
    assert config.profile_names == ["cost", "quality"]
    assert config.active_profile in config.profile_names


def test_every_profile_covers_every_task():
    """A missing task only fails at runtime, three agents into a request."""
    config = load_routing_config()
    for name in config.profile_names:
        assert set(config.profiles[name]) == TASKS, f"profile {name} is incomplete"


def test_every_route_has_at_least_one_fallback():
    config = load_routing_config()
    for name in config.profile_names:
        for task, route in config.profiles[name].items():
            assert route.fallbacks, f"{name}.{task} has no fallback candidate"


def test_cost_profile_keeps_the_strong_model_for_drafting():
    """The draft is the deliverable; the cost profile downgrades around it."""
    config = load_routing_config()
    assert config.profiles["cost"]["draft"].primary.model == "claude-opus-5"
    assert config.profiles["cost"]["parse"].primary.model != "claude-opus-5"


def test_unknown_profile_raises_with_the_available_names():
    config = load_routing_config()
    with pytest.raises(ValueError, match="unknown routing profile"):
        config.route("draft", "nope")


def test_unknown_task_raises_with_the_available_names():
    config = load_routing_config()
    with pytest.raises(ValueError, match="no entry for task"):
        config.route("nonexistent")


def test_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_routing_config(tmp_path / "absent.yaml")


def test_config_with_no_profiles_is_rejected(tmp_path):
    path = tmp_path / "mcp.yaml"
    path.write_text("active_profile: quality\nprofiles: {}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="no profiles"):
        load_routing_config(path)


def test_route_without_primary_is_rejected(tmp_path):
    path = tmp_path / "mcp.yaml"
    path.write_text(
        "profiles:\n  quality:\n    parse:\n      fallbacks: []\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="missing 'primary'"):
        load_routing_config(path)


def test_malformed_candidate_is_rejected(tmp_path):
    path = tmp_path / "mcp.yaml"
    path.write_text(
        "profiles:\n  quality:\n    parse:\n      primary: {provider: anthropic}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="provider"):
        load_routing_config(path)


def test_active_profile_must_exist(tmp_path):
    path = tmp_path / "mcp.yaml"
    path.write_text(
        "active_profile: missing\n"
        "profiles:\n  quality:\n    parse:\n      primary: {provider: a, model: m}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="active_profile"):
        load_routing_config(path)


def test_every_tone_has_a_sample_file():
    """The stylist degrades without one, so a missing file is a silent quality
    regression rather than a crash. Assert it here instead."""
    for tone in Tone:
        assert (TONE_SAMPLES_DIR / f"{tone.value}.md").exists(), f"no sample for {tone.value}"
        assert load_tone_sample(tone.value), f"empty sample for {tone.value}"


def test_missing_tone_sample_degrades_quietly():
    assert load_tone_sample("no-such-tone") == ""


def test_config_path_resolves_independently_of_cwd():
    assert MCP_CONFIG_PATH.is_absolute()
    assert MCP_CONFIG_PATH.exists()
