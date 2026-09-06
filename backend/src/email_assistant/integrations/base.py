"""The provider contract and a normalized error taxonomy.

Every provider raises errors from this module, never its own SDK's. That is the
whole point of the layer: the router decides whether to fall back by looking at
one small set of exception types, so adding a third provider later cannot change
the routing logic. Translating an SDK error into the wrong class here is the one
mistake that would silently break fallback, so each translation is explicit.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Protocol, Type, runtime_checkable

from pydantic import BaseModel


class LLMError(Exception):
    """Base for every provider failure."""


class RetryableError(LLMError):
    """The request failed for a reason another model or another attempt may survive.

    Rate limits, 5xx, connection drops, and policy refusals all land here. So does
    a schema-validation failure: a model that would not produce the requested
    shape has not answered, and the next candidate deserves a turn.
    """


class FatalError(LLMError):
    """The request itself is malformed. Retrying cannot help.

    A 400 means we built a bad request. Falling back would hide our own bug behind
    a second model's identical rejection, so this class is never retried.
    """


class ProviderUnavailable(LLMError):
    """The provider has no usable credential, so it is skipped rather than tried.

    Separate from RetryableError because it is not a failure — it is the normal
    state of a provider the user has not configured, and it should not appear in
    the trace as an error the user needs to care about.
    """


class NoCandidatesAvailable(LLMError):
    """Every candidate for a task was exhausted or unavailable."""


@dataclass
class LLMResult:
    """One successful completion."""

    text: str
    parsed: Optional[BaseModel]
    provider: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    raw: Optional[Any] = None


@runtime_checkable
class LLMProvider(Protocol):
    """What the router needs from a provider."""

    name: str

    def available(self) -> bool:
        """True when this provider has a credential and can be tried."""
        ...

    def complete(
        self,
        *,
        model: str,
        system: str,
        user: str,
        schema: Optional[Type[BaseModel]] = None,
        max_tokens: int = 16000,
    ) -> LLMResult:
        """Run one completion, or raise something from this module."""
        ...
