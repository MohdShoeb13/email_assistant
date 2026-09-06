"""Settings, paths, and the parsed model-routing table.

Paths are resolved from this file's location rather than the working directory,
because the app is started three different ways (pytest from the repo root,
uvicorn from backend/, the CLI from anywhere) and a relative data path would
silently resolve to a different profiles.json in each.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

import yaml
from dotenv import load_dotenv

# src/email_assistant/config.py -> src/email_assistant -> src -> backend
BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_DIR.parent
DATA_DIR = BACKEND_DIR / "data"
CONFIG_DIR = BACKEND_DIR / "config"
TONE_SAMPLES_DIR = DATA_DIR / "tone_samples"
PROFILES_PATH = DATA_DIR / "profiles.json"
USAGE_LOG_PATH = DATA_DIR / "usage_log.jsonl"
MCP_CONFIG_PATH = CONFIG_DIR / "mcp.yaml"

# The .env lives at the repo root so both halves of the app read one file.
load_dotenv(REPO_ROOT / ".env")


def _truthy(value: Optional[str]) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Candidate:
    """One (provider, model) pair the router may try."""

    provider: str
    model: str


@dataclass(frozen=True)
class TaskRoute:
    """The ordered candidate list for a single agent task."""

    task: str
    primary: Candidate
    fallbacks: tuple[Candidate, ...] = ()

    @property
    def candidates(self) -> tuple[Candidate, ...]:
        return (self.primary, *self.fallbacks)


@dataclass(frozen=True)
class RetryConfig:
    max_attempts: int = 3
    base_delay_seconds: float = 1.0
    max_delay_seconds: float = 8.0


@dataclass(frozen=True)
class RoutingConfig:
    """The whole mcp.yaml, parsed and validated."""

    active_profile: str
    profiles: dict[str, dict[str, TaskRoute]] = field(default_factory=dict)
    retry: RetryConfig = field(default_factory=RetryConfig)

    def route(self, task: str, profile: Optional[str] = None) -> TaskRoute:
        name = profile or self.active_profile
        if name not in self.profiles:
            raise ValueError(
                f"unknown routing profile {name!r}; available: {sorted(self.profiles)}"
            )
        routes = self.profiles[name]
        if task not in routes:
            raise ValueError(
                f"routing profile {name!r} has no entry for task {task!r}; "
                f"available: {sorted(routes)}"
            )
        return routes[task]

    @property
    def profile_names(self) -> list[str]:
        return sorted(self.profiles)


def _parse_candidate(raw: Any, where: str) -> Candidate:
    if not isinstance(raw, dict) or "provider" not in raw or "model" not in raw:
        raise ValueError(f"{where}: expected a mapping with 'provider' and 'model', got {raw!r}")
    return Candidate(provider=str(raw["provider"]), model=str(raw["model"]))


def load_routing_config(path: Optional[Path] = None) -> RoutingConfig:
    """Parse mcp.yaml into typed routes.

    Validation is strict and happens at load time: a typo in a provider name
    should fail on startup, not three agents into a user's first request.
    """
    path = path or MCP_CONFIG_PATH
    if not path.exists():
        raise FileNotFoundError(f"routing config not found at {path}")

    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    raw_profiles = raw.get("profiles") or {}
    if not raw_profiles:
        raise ValueError(f"{path}: no profiles defined")

    profiles: dict[str, dict[str, TaskRoute]] = {}
    for profile_name, tasks in raw_profiles.items():
        if not isinstance(tasks, dict) or not tasks:
            raise ValueError(f"{path}: profile {profile_name!r} defines no tasks")
        parsed_tasks: dict[str, TaskRoute] = {}
        for task_name, spec in tasks.items():
            where = f"{path}: profiles.{profile_name}.{task_name}"
            if not isinstance(spec, dict) or "primary" not in spec:
                raise ValueError(f"{where}: missing 'primary'")
            fallbacks = tuple(
                _parse_candidate(item, f"{where}.fallbacks[{i}]")
                for i, item in enumerate(spec.get("fallbacks") or [])
            )
            parsed_tasks[task_name] = TaskRoute(
                task=task_name,
                primary=_parse_candidate(spec["primary"], f"{where}.primary"),
                fallbacks=fallbacks,
            )
        profiles[profile_name] = parsed_tasks

    active = str(raw.get("active_profile") or next(iter(profiles)))
    if active not in profiles:
        raise ValueError(f"{path}: active_profile {active!r} is not one of {sorted(profiles)}")

    retry_raw = raw.get("retry") or {}
    retry = RetryConfig(
        max_attempts=int(retry_raw.get("max_attempts", 3)),
        base_delay_seconds=float(retry_raw.get("base_delay_seconds", 1.0)),
        max_delay_seconds=float(retry_raw.get("max_delay_seconds", 8.0)),
    )
    return RoutingConfig(active_profile=active, profiles=profiles, retry=retry)


@dataclass(frozen=True)
class Settings:
    """Everything the app reads from the environment."""

    fake_llm: bool
    anthropic_api_key: Optional[str]
    openai_api_key: Optional[str]
    routing_profile: str
    max_tokens: int
    request_timeout_seconds: float

    @property
    def offline(self) -> bool:
        """True when no real model can be reached, so the fake provider is used.

        Being keyless is treated as offline rather than as an error: the whole
        point of the fake provider is that a fresh clone runs and demos with no
        setup at all.
        """
        return self.fake_llm or not (self.anthropic_api_key or self.openai_api_key)


def load_settings() -> Settings:
    return Settings(
        fake_llm=_truthy(os.getenv("FAKE_LLM")),
        anthropic_api_key=(os.getenv("ANTHROPIC_API_KEY") or "").strip() or None,
        openai_api_key=(os.getenv("OPENAI_API_KEY") or "").strip() or None,
        routing_profile=(os.getenv("ROUTING_PROFILE") or "quality").strip(),
        max_tokens=int(os.getenv("MAX_TOKENS") or 16000),
        request_timeout_seconds=float(os.getenv("REQUEST_TIMEOUT_SECONDS") or 120.0),
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return load_settings()


@lru_cache(maxsize=1)
def get_routing_config() -> RoutingConfig:
    return load_routing_config()


def reset_caches() -> None:
    """Drop cached settings. Tests use this after changing the environment."""
    get_settings.cache_clear()
    get_routing_config.cache_clear()


@lru_cache(maxsize=16)
def load_tone_sample(tone: str) -> str:
    """Read a tone exemplar file, or return an empty string if it is absent.

    A missing sample degrades the prompt rather than failing the request: the
    tone name alone still produces a usable draft.
    """
    path = TONE_SAMPLES_DIR / f"{tone}.md"
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()
