"""Anthropic provider.

Uses messages.parse() with a Pydantic output_format, which constrains the response
at the API level and returns a validated instance. Doing schema enforcement server
-side rather than parsing JSON out of prose is what makes a validation failure rare
enough to be worth treating as a fallback trigger.

Deliberately absent: budget_tokens (removed on Opus 5, returns 400) and assistant
prefill (also 400 on current models). Thinking is left at the default, which is
adaptive on Opus 5.
"""

from __future__ import annotations


from typing import Optional, Type

import anthropic
from pydantic import BaseModel, ValidationError

from ..config import get_settings
from .base import FatalError, LLMResult, ProviderUnavailable, RetryableError

DEFAULT_MODEL = "claude-opus-5"


class AnthropicProvider:
    """Anthropic Claude via the official SDK."""

    name = "anthropic"

    def __init__(self, api_key: Optional[str] = None, timeout: Optional[float] = None) -> None:
        settings = get_settings()
        self._api_key = api_key if api_key is not None else settings.anthropic_api_key
        self._timeout = timeout if timeout is not None else settings.request_timeout_seconds
        self._client: Optional[anthropic.Anthropic] = None

    def available(self) -> bool:
        return bool(self._api_key)

    def _get_client(self) -> anthropic.Anthropic:
        if self._client is None:
            if not self._api_key:
                raise ProviderUnavailable("anthropic: no ANTHROPIC_API_KEY configured")
            # max_retries=0 because the router owns retry policy. Leaving the SDK
            # default of 2 would silently triple the latency of a rate-limited
            # call before the router ever got the chance to try a cheaper model.
            self._client = anthropic.Anthropic(
                api_key=self._api_key, timeout=self._timeout, max_retries=0
            )
        return self._client

    def complete(
        self,
        *,
        model: str = DEFAULT_MODEL,
        system: str,
        user: str,
        schema: Optional[Type[BaseModel]] = None,
        max_tokens: int = 16000,
    ) -> LLMResult:
        client = self._get_client()


        try:
            if schema is not None:
                response = client.messages.parse(
                    model=model,
                    max_tokens=max_tokens,
                    system=system,
                    messages=[{"role": "user", "content": user}],
                    output_format=schema,
                )
            else:
                response = client.messages.create(
                    model=model,
                    max_tokens=max_tokens,
                    system=system,
                    messages=[{"role": "user", "content": user}],
                )
        except anthropic.NotFoundError as exc:
            # A wrong model id is a config error, but the next candidate may well
            # be a valid model, so this is worth falling back on rather than fatal.
            raise RetryableError(f"anthropic: unknown model {model!r}: {exc}") from exc
        except anthropic.AuthenticationError as exc:
            raise ProviderUnavailable(f"anthropic: credential rejected: {exc}") from exc
        except anthropic.PermissionDeniedError as exc:
            raise ProviderUnavailable(f"anthropic: key lacks access to {model!r}: {exc}") from exc
        except anthropic.BadRequestError as exc:
            raise FatalError(f"anthropic: malformed request: {exc}") from exc
        except anthropic.RateLimitError as exc:
            raise RetryableError(f"anthropic: rate limited: {exc}") from exc
        except anthropic.APIStatusError as exc:
            if exc.status_code >= 500:
                raise RetryableError(f"anthropic: server error {exc.status_code}: {exc}") from exc
            raise FatalError(f"anthropic: api error {exc.status_code}: {exc}") from exc
        except anthropic.APIConnectionError as exc:
            raise RetryableError(f"anthropic: connection failed: {exc}") from exc

        # Check the stop reason before touching content: on a refusal the content
        # blocks are not the answer, and reading them yields a misleading result.
        if getattr(response, "stop_reason", None) == "refusal":
            details = getattr(response, "stop_details", None)
            category = getattr(details, "category", None) if details else None
            raise RetryableError(f"anthropic: model declined the request (category={category})")

        usage = getattr(response, "usage", None)

        parsed: Optional[BaseModel] = None
        if schema is not None:
            parsed = getattr(response, "parsed_output", None)
            if parsed is None:
                raise RetryableError(
                    f"anthropic: {model} returned no parsed output for {schema.__name__}"
                )
            if not isinstance(parsed, schema):
                try:
                    parsed = schema.model_validate(parsed)
                except ValidationError as exc:
                    raise RetryableError(
                        f"anthropic: {model} output failed {schema.__name__} validation: {exc}"
                    ) from exc

        text = "".join(
            block.text for block in getattr(response, "content", []) if getattr(block, "type", "") == "text"
        )

        return LLMResult(
            text=text,
            parsed=parsed,
            provider=self.name,
            model=model,
            input_tokens=getattr(usage, "input_tokens", 0) or 0,
            output_tokens=getattr(usage, "output_tokens", 0) or 0,
            raw=response,
        )
