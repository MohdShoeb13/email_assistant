"""OpenAI provider.

The cross-provider half of the fallback chain. Uses chat.completions.parse() with
a Pydantic response_format, which is the OpenAI equivalent of the Anthropic path:
schema enforced server-side, a validated instance back.

Errors are translated into the same taxonomy as every other provider, so the
router never learns that a second SDK exists.
"""

from __future__ import annotations

from typing import Optional, Type

import openai
from pydantic import BaseModel, ValidationError

from ..config import get_settings
from .base import FatalError, LLMResult, ProviderUnavailable, RetryableError

DEFAULT_MODEL = "gpt-4o"


class OpenAIProvider:
    """OpenAI via the official SDK."""

    name = "openai"

    def __init__(self, api_key: Optional[str] = None, timeout: Optional[float] = None) -> None:
        settings = get_settings()
        self._api_key = api_key if api_key is not None else settings.openai_api_key
        self._timeout = timeout if timeout is not None else settings.request_timeout_seconds
        self._client: Optional[openai.OpenAI] = None

    def available(self) -> bool:
        return bool(self._api_key)

    def _get_client(self) -> openai.OpenAI:
        if self._client is None:
            if not self._api_key:
                raise ProviderUnavailable("openai: no OPENAI_API_KEY configured")
            # max_retries=0 for the same reason as the Anthropic client: the
            # router decides when to give up on a model, not the SDK.
            self._client = openai.OpenAI(
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
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

        try:
            if schema is not None:
                response = client.chat.completions.parse(
                    model=model,
                    messages=messages,
                    response_format=schema,
                    max_tokens=max_tokens,
                )
            else:
                response = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    max_tokens=max_tokens,
                )
        except openai.NotFoundError as exc:
            raise RetryableError(f"openai: unknown model {model!r}: {exc}") from exc
        except openai.AuthenticationError as exc:
            raise ProviderUnavailable(f"openai: credential rejected: {exc}") from exc
        except openai.PermissionDeniedError as exc:
            raise ProviderUnavailable(f"openai: key lacks access to {model!r}: {exc}") from exc
        except openai.BadRequestError as exc:
            raise FatalError(f"openai: malformed request: {exc}") from exc
        except openai.RateLimitError as exc:
            raise RetryableError(f"openai: rate limited: {exc}") from exc
        except openai.APIStatusError as exc:
            if exc.status_code >= 500:
                raise RetryableError(f"openai: server error {exc.status_code}: {exc}") from exc
            raise FatalError(f"openai: api error {exc.status_code}: {exc}") from exc
        except openai.APIConnectionError as exc:
            raise RetryableError(f"openai: connection failed: {exc}") from exc

        choice = response.choices[0] if response.choices else None
        if choice is None:
            raise RetryableError(f"openai: {model} returned no choices")

        message = choice.message

        # Check refusal before content, same reasoning as the Anthropic client:
        # on a refusal, .content is not the answer.
        if getattr(message, "refusal", None):
            raise RetryableError(f"openai: model declined the request: {message.refusal}")

        parsed: Optional[BaseModel] = None
        if schema is not None:
            parsed = getattr(message, "parsed", None)
            if parsed is None:
                raise RetryableError(
                    f"openai: {model} returned no parsed output for {schema.__name__}"
                )
            if not isinstance(parsed, schema):
                try:
                    parsed = schema.model_validate(parsed)
                except ValidationError as exc:
                    raise RetryableError(
                        f"openai: {model} output failed {schema.__name__} validation: {exc}"
                    ) from exc

        usage = getattr(response, "usage", None)
        return LLMResult(
            text=message.content or "",
            parsed=parsed,
            provider=self.name,
            model=model,
            input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            output_tokens=getattr(usage, "completion_tokens", 0) or 0,
            raw=response,
        )
