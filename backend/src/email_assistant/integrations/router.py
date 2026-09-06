"""The model control plane: candidate selection, fallback, and the usage trace.

Every agent calls this and nothing else. It reads the route for a task from
mcp.yaml, walks the candidates in order, and returns the first success — recording
every attempt, including the failures, because the failures are the only evidence
that fallback occurred.

The one rule worth stating plainly: a FatalError stops the walk. A 400 means we
built a malformed request, and trying the same malformed request against a second
model would turn our own bug into a slow, expensive, identical failure that looks
like a provider outage. Everything else is worth another candidate's turn.
"""

from __future__ import annotations

import json
import random
import threading
import time
from typing import Any, Callable, Optional, Type

from pydantic import BaseModel

from ..config import USAGE_LOG_PATH, Candidate, RoutingConfig, Settings, get_routing_config, get_settings
from ..state import ModelCall
from .anthropic_client import AnthropicProvider
from .base import (
    FatalError,
    LLMProvider,
    LLMResult,
    NoCandidatesAvailable,
    ProviderUnavailable,
    RetryableError,
)
from .fake_client import FakeProvider
from .openai_client import OpenAIProvider

# Serializes appends to the usage log. The API server runs the graph in a
# threadpool, so two concurrent requests can otherwise interleave partial lines
# and corrupt the JSONL.
_LOG_LOCK = threading.Lock()


class ModelRouter:
    """Routes one agent task to a working model, and records what happened."""

    def __init__(
        self,
        *,
        settings: Optional[Settings] = None,
        routing: Optional[RoutingConfig] = None,
        providers: Optional[dict[str, LLMProvider]] = None,
        profile: Optional[str] = None,
        usage_log_path: Optional[Any] = None,
        on_call: Optional[Callable[[ModelCall], None]] = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.routing = routing or get_routing_config()
        self.profile = profile or self.settings.routing_profile or self.routing.active_profile
        self.usage_log_path = usage_log_path if usage_log_path is not None else USAGE_LOG_PATH
        # Lets the API layer push a model_call SSE frame the moment an attempt
        # finishes, rather than only after the whole node returns.
        self.on_call = on_call
        self.calls: list[ModelCall] = []
        self._providers = providers if providers is not None else self._build_providers()

    def _build_providers(self) -> dict[str, LLMProvider]:
        if self.settings.offline:
            # In offline mode the fake provider answers for every provider name,
            # so a route naming anthropic or openai still resolves and the
            # candidate walk stays identical to the live path.
            fake = FakeProvider()
            return {"anthropic": fake, "openai": fake, "fake": fake}
        return {
            "anthropic": AnthropicProvider(),
            "openai": OpenAIProvider(),
            "fake": FakeProvider(),
        }

    # --- introspection ------------------------------------------------------

    def provider_status(self) -> dict[str, bool]:
        """Which providers could actually serve a request right now."""
        return {name: provider.available() for name, provider in self._providers.items()}

    def candidates_for(self, task: str) -> tuple[Candidate, ...]:
        return self.routing.route(task, self.profile).candidates

    # --- the main path ------------------------------------------------------

    def complete(
        self,
        *,
        task: str,
        system: str,
        user: str,
        schema: Optional[Type[BaseModel]] = None,
        max_tokens: Optional[int] = None,
    ) -> LLMResult:
        """Try each candidate for `task` until one succeeds."""
        route = self.routing.route(task, self.profile)
        max_tokens = max_tokens or self.settings.max_tokens
        retry = self.routing.retry

        skipped: list[str] = []
        failures: list[str] = []
        attempt_number = 0

        for position, candidate in enumerate(route.candidates):
            provider = self._providers.get(candidate.provider)
            if provider is None:
                skipped.append(f"{candidate.provider} (no such provider)")
                continue
            if not provider.available():
                # Not an error. An unconfigured provider is the normal state, so
                # it is skipped silently rather than logged as a failed attempt.
                skipped.append(f"{candidate.provider} (no credential)")
                continue

            is_fallback = position > 0
            for local_attempt in range(1, retry.max_attempts + 1):
                attempt_number += 1
                started = time.monotonic()
                try:
                    result = provider.complete(
                        model=candidate.model,
                        system=system,
                        user=user,
                        schema=schema,
                        max_tokens=max_tokens,
                    )
                except ProviderUnavailable as exc:
                    # The credential turned out to be bad at call time. Abandon
                    # this provider entirely rather than burning its retries.
                    skipped.append(f"{candidate.provider} ({exc})")
                    break
                except FatalError as exc:
                    self._record(
                        task, candidate, attempt_number, "error", started,
                        error=exc, is_fallback=is_fallback,
                    )
                    raise
                except RetryableError as exc:
                    self._record(
                        task, candidate, attempt_number, "error", started,
                        error=exc, is_fallback=is_fallback,
                    )
                    failures.append(f"{candidate.provider}/{candidate.model}: {exc}")
                    if local_attempt < retry.max_attempts:
                        time.sleep(self._backoff(local_attempt, retry.base_delay_seconds, retry.max_delay_seconds))
                        continue
                    break
                else:
                    self._record(
                        task, candidate, attempt_number, "success", started,
                        result=result, is_fallback=is_fallback,
                    )
                    return result

        raise NoCandidatesAvailable(
            f"task {task!r} (profile {self.profile!r}) exhausted every candidate. "
            f"Skipped: {skipped or 'none'}. Failed: {failures or 'none'}."
        )

    @staticmethod
    def _backoff(attempt: int, base: float, ceiling: float) -> float:
        """Exponential backoff with jitter.

        Jitter matters because all five agent tasks share one rate limit; without
        it, a burst that gets limited retries in lockstep and gets limited again.
        """
        return min(base * (2 ** (attempt - 1)) + random.uniform(0, base / 2), ceiling)

    # --- trace --------------------------------------------------------------

    def _record(
        self,
        task: str,
        candidate: Candidate,
        attempt: int,
        outcome: str,
        started: float,
        *,
        result: Optional[LLMResult] = None,
        error: Optional[Exception] = None,
        is_fallback: bool = False,
    ) -> None:
        call = ModelCall(
            task=task,
            provider=candidate.provider,
            model=candidate.model,
            attempt=attempt,
            outcome="success" if outcome == "success" else "error",
            latency_ms=int((time.monotonic() - started) * 1000),
            input_tokens=result.input_tokens if result else 0,
            output_tokens=result.output_tokens if result else 0,
            error_type=type(error).__name__ if error else None,
            error_message=str(error)[:300] if error else None,
            is_fallback=is_fallback,
        )
        self.calls.append(call)
        self._append_usage_log(call)
        if self.on_call is not None:
            self.on_call(call)

    def _append_usage_log(self, call: ModelCall) -> None:
        """Append one JSONL line. Never raises.

        Telemetry must not be able to fail a user's request: a read-only data
        directory should cost the trace file, not the draft.
        """
        if self.usage_log_path is None:
            return
        try:
            payload = call.model_dump()
            payload["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
            payload["profile"] = self.profile
            with _LOG_LOCK:
                self.usage_log_path.parent.mkdir(parents=True, exist_ok=True)
                with open(self.usage_log_path, "a", encoding="utf-8") as handle:
                    handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
        except OSError:
            pass

    def trace(self) -> list[dict[str, Any]]:
        return [call.model_dump() for call in self.calls]
