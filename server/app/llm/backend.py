from __future__ import annotations

import json
import logging
import os
import threading
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Generic, Iterator, Protocol, Sequence, TypeVar, cast

import openai
from app.database.models import ReasoningLevel
from app.llm.pydantic_models import profile_for_reasoning
from app.llm.token_credits import settle_token_usage
from app.modules.papers.application.contracts.extraction import (
    FileContent,
    SupplementaryContent,
    TextContent,
    ToolCall,
    ToolCallResult,
)
from openai.types.chat import ChatCompletionMessageParam, ChatCompletionToolParam
from scholens_observability import add_counter, instrumented_span, record_histogram
from scholens_ai import AIProfile, AIThinkingMode

logger = logging.getLogger(__name__)
T = TypeVar("T")


class LLMUsageSettlementError(RuntimeError):
    """Provider usage was received but could not be durably recorded."""


class _StreamCancellation:
    """Thread-safe cancellation of the provider response, not its generator."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cancelled = False
        self._close_provider: Callable[[], None] | None = None

    def attach(self, close_provider: Callable[[], None]) -> None:
        with self._lock:
            self._close_provider = close_provider
            cancelled = self._cancelled
        if cancelled:
            close_provider()

    def detach(self) -> None:
        with self._lock:
            self._close_provider = None

    def cancel(self) -> None:
        with self._lock:
            self._cancelled = True
            close_provider = self._close_provider
        if close_provider is not None:
            close_provider()

    @property
    def cancelled(self) -> bool:
        with self._lock:
            return self._cancelled


class _CancellableIterator(Iterator[T], Generic[T]):
    """Keep generator ownership in its reader thread while exposing safe I/O cancel."""

    def __init__(
        self,
        factory: Callable[[_StreamCancellation], Iterator[T]],
    ) -> None:
        self._cancellation = _StreamCancellation()
        self._iterator = factory(self._cancellation)

    def __iter__(self) -> _CancellableIterator[T]:
        return self

    def __next__(self) -> T:
        if self._cancellation.cancelled:
            raise StopIteration
        return next(self._iterator)

    def cancel(self) -> None:
        self._cancellation.cancel()

    def close(self) -> None:
        self._cancellation.cancel()
        close_iterator = getattr(self._iterator, "close", None)
        if callable(close_iterator):
            close_iterator()


@dataclass(slots=True)
class LLMResponse:
    text: str
    thinking: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    malformed_tool_calls: list[MalformedToolCall] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class MalformedToolCall:
    """Provider tool identity retained when its arguments are not valid JSON."""

    id: str | None
    name: str


@dataclass(frozen=True, slots=True)
class StreamChunk:
    text: str
    is_done: bool = False
    thinking: str | None = None


MessageContent = TextContent | FileContent | SupplementaryContent
MessageParam = str | Sequence[MessageContent]


class HistoryMessage(Protocol):
    @property
    def role(self) -> str: ...

    @property
    def content(self) -> str: ...


class LLMBackend(ABC):
    @abstractmethod
    def model_revision(
        self,
        reasoning_level: ReasoningLevel = ReasoningLevel.STANDARD,
    ) -> str: ...

    @abstractmethod
    def generate_content(
        self,
        contents: MessageParam,
        reasoning_level: ReasoningLevel = ReasoningLevel.STANDARD,
        system_prompt: str | None = None,
        history: Sequence[HistoryMessage] | None = None,
        function_declarations: list[dict[str, Any]] | None = None,
        tool_call_results: list[ToolCallResult] | None = None,
        schema: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> LLMResponse: ...

    @abstractmethod
    def send_message_stream(
        self,
        message: MessageParam,
        history: Sequence[HistoryMessage],
        system_prompt: str,
        reasoning_level: ReasoningLevel = ReasoningLevel.STANDARD,
        file: FileContent | None = None,
        **kwargs: Any,
    ) -> Iterator[StreamChunk]: ...


def _usage_value(usage: Any, name: str) -> int:
    value = getattr(usage, name, 0) if usage is not None else 0
    return int(value or 0)


def _completion_detail(usage: Any, name: str) -> int:
    details = getattr(usage, "completion_tokens_details", None)
    return _usage_value(details, name)


class ProfiledChatBackend(LLMBackend):
    """Synchronous adapter for Scholens profiles using chat-compatible providers.

    New orchestration uses Pydantic AI directly. This adapter remains intentionally
    narrow for synchronous citation recovery and title generation.
    """

    def __init__(self) -> None:
        self._profiles = {
            level: profile_for_reasoning(level)
            for level in (ReasoningLevel.STANDARD, ReasoningLevel.DEEP)
        }
        self._clients = {
            level: self._new_client(profile)
            for level, profile in self._profiles.items()
        }
        self._max_output_tokens = self._profiles[
            ReasoningLevel.STANDARD
        ].max_output_tokens

    @staticmethod
    def _new_client(profile: AIProfile) -> openai.OpenAI:
        if profile.provider not in {"deepseek", "moonshotai"}:
            raise ValueError(
                f"Profile {profile.name.value} selects {profile.provider}, which "
                "does not expose the synchronous chat-compatible interface"
            )
        prefix = f"SCHOLENS_AI_{profile.provider.upper()}"
        api_key = os.getenv(f"{prefix}_API_KEY")
        if not api_key:
            raise ValueError(f"{prefix}_API_KEY is required")
        default_base_urls = {
            "deepseek": "https://api.deepseek.com",
            "moonshotai": "https://api.moonshot.ai/v1",
        }
        return openai.OpenAI(
            api_key=api_key,
            base_url=os.getenv(
                f"{prefix}_BASE_URL", default_base_urls.get(profile.provider)
            ),
            timeout=profile.request_timeout_seconds,
            max_retries=profile.max_retries,
        )

    def _profile(self, reasoning_level: ReasoningLevel) -> AIProfile:
        return self._profiles[reasoning_level]

    def _model(self, reasoning_level: ReasoningLevel) -> str:
        return self._profile(reasoning_level).model_id

    def _client(self, reasoning_level: ReasoningLevel) -> openai.OpenAI:
        return self._clients[reasoning_level]

    def model_revision(
        self,
        reasoning_level: ReasoningLevel = ReasoningLevel.STANDARD,
    ) -> str:
        return self._profile(reasoning_level).revision

    def _thinking_body(self, reasoning_level: ReasoningLevel) -> dict[str, Any]:
        profile = self._profile(reasoning_level)
        if profile.thinking is AIThinkingMode.ENABLED:
            return {
                "thinking": {"type": "enabled"},
                "reasoning_effort": profile.thinking_effort.value,
            }
        return {"thinking": {"type": "disabled"}}

    def _settle(
        self,
        *,
        profile: AIProfile,
        response_id: str | None,
        usage: Any,
    ) -> None:
        try:
            if usage is None:
                logger.warning("llm.usage.missing", extra={"model": profile.model_id})
                settle_token_usage(
                    provider=profile.provider,
                    model=profile.model_id,
                    ai_profile=profile.name.value,
                    thinking=profile.thinking.value,
                    thinking_effort=profile.thinking_effort.value,
                    profile_revision=profile.revision,
                    provider_request_id=response_id,
                    prompt_tokens=0,
                    completion_tokens=0,
                    total_tokens=0,
                    idempotency_key=(
                        f"{profile.provider}:{response_id}" if response_id else None
                    ),
                    status="unknown",
                )
                add_counter(
                    "scholens.llm.usage_unknown",
                    attributes={
                        "provider": profile.provider,
                        "model": profile.model_id,
                        "ai_profile": profile.name.value,
                    },
                )
                return
            token_values = {
                "prompt": _usage_value(usage, "prompt_tokens"),
                "completion": _usage_value(usage, "completion_tokens"),
                "reasoning": _completion_detail(usage, "reasoning_tokens"),
                "cache_hit": _usage_value(usage, "prompt_cache_hit_tokens"),
                "cache_miss": _usage_value(usage, "prompt_cache_miss_tokens"),
            }
            settle_token_usage(
                provider=profile.provider,
                model=profile.model_id,
                ai_profile=profile.name.value,
                thinking=profile.thinking.value,
                thinking_effort=profile.thinking_effort.value,
                profile_revision=profile.revision,
                provider_request_id=response_id,
                prompt_tokens=_usage_value(usage, "prompt_tokens"),
                completion_tokens=_usage_value(usage, "completion_tokens"),
                reasoning_tokens=_completion_detail(usage, "reasoning_tokens"),
                cache_hit_tokens=_usage_value(usage, "prompt_cache_hit_tokens"),
                cache_miss_tokens=_usage_value(usage, "prompt_cache_miss_tokens"),
                total_tokens=_usage_value(usage, "total_tokens"),
                idempotency_key=(
                    f"{profile.provider}:{response_id}" if response_id else None
                ),
            )
            for token_kind, token_count in token_values.items():
                if token_count > 0:
                    add_counter(
                        "scholens.llm.tokens",
                        token_count,
                        attributes={
                            "provider": profile.provider,
                            "model": profile.model_id,
                            "ai_profile": profile.name.value,
                            "token_kind": token_kind,
                        },
                    )
        except Exception as exc:
            add_counter(
                "scholens.llm.usage_settlement_failures",
                attributes={"provider": profile.provider},
            )
            raise LLMUsageSettlementError(
                "LLM token usage could not be settled"
            ) from exc

    def generate_content(
        self,
        contents: MessageParam,
        reasoning_level: ReasoningLevel = ReasoningLevel.STANDARD,
        system_prompt: str | None = None,
        history: Sequence[HistoryMessage] | None = None,
        function_declarations: list[dict[str, Any]] | None = None,
        tool_call_results: list[ToolCallResult] | None = None,
        schema: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        profile = self._profile(reasoning_level)
        model = self._model(reasoning_level)
        prompt = system_prompt or ""
        if schema:
            prompt = (
                f"{prompt}\n\nReturn one valid JSON object matching this schema exactly:\n"
                f"{json.dumps(schema, ensure_ascii=False)}"
            )
            kwargs["response_format"] = {"type": "json_object"}

        messages = self._prepare_messages(
            history=history or [],
            new_message=contents,
            system_prompt=prompt,
            tool_call_results=tool_call_results,
        )
        if function_declarations:
            kwargs["tools"] = [
                self._cast_tool_declaration(item) for item in function_declarations
            ]
        kwargs.setdefault("max_tokens", self._max_output_tokens)
        started = time.monotonic()
        status = "success"
        try:
            with instrumented_span(
                "llm.generate",
                attributes={
                    "gen_ai.system": profile.provider,
                    "gen_ai.request.model": model,
                    "scholens.reasoning_level": reasoning_level.value,
                    "scholens.llm.streaming": False,
                },
            ):
                response = self._client(reasoning_level).chat.completions.create(
                    model=model,
                    messages=messages,
                    extra_body=self._thinking_body(reasoning_level),
                    **kwargs,
                )
        except BaseException:
            status = "failure"
            raise
        finally:
            attributes = {
                "provider": profile.provider,
                "model": model,
                "ai_profile": profile.name.value,
                "streaming": False,
                "status": status,
            }
            add_counter("scholens.llm.requests", attributes=attributes)
            record_histogram(
                "scholens.llm.duration",
                (time.monotonic() - started) * 1000,
                attributes=attributes,
            )
            logger.info(
                "llm.request.completed",
                extra={
                    **attributes,
                    "duration_ms": round((time.monotonic() - started) * 1000, 3),
                },
            )
        if not response.choices:
            raise ValueError("AI provider returned no choices")
        message = response.choices[0].message
        self._settle(
            profile=profile,
            response_id=getattr(response, "id", None),
            usage=response.usage,
        )
        tool_calls: list[ToolCall] = []
        malformed_tool_calls: list[MalformedToolCall] = []
        for call in message.tool_calls or []:
            try:
                arguments = json.loads(call.function.arguments or "{}")
                if not isinstance(arguments, dict):
                    raise TypeError("tool arguments must be a JSON object")
                tool_calls.append(
                    ToolCall(
                        id=call.id,
                        name=call.function.name,
                        args=arguments,
                    )
                )
            except (json.JSONDecodeError, TypeError, ValueError):
                logger.warning(
                    "llm.tool_arguments.invalid",
                    extra={"tool_name": call.function.name},
                )
                malformed_tool_calls.append(
                    MalformedToolCall(
                        id=call.id,
                        name=call.function.name,
                    )
                )
        thinking = getattr(message, "reasoning_content", None)
        return LLMResponse(
            text=message.content or "",
            thinking=thinking if isinstance(thinking, str) else None,
            tool_calls=tool_calls,
            malformed_tool_calls=malformed_tool_calls,
        )

    def send_message_stream(
        self,
        message: MessageParam,
        history: Sequence[HistoryMessage],
        system_prompt: str,
        reasoning_level: ReasoningLevel = ReasoningLevel.STANDARD,
        file: FileContent | None = None,
        **kwargs: Any,
    ) -> Iterator[StreamChunk]:
        profile = self._profile(reasoning_level)
        model = self._model(reasoning_level)
        messages = self._prepare_messages(
            history=history,
            new_message=message,
            system_prompt=system_prompt,
            file=file,
        )
        kwargs.setdefault("max_tokens", self._max_output_tokens)

        def stream_chunks(
            cancellation: _StreamCancellation,
        ) -> Iterator[StreamChunk]:
            started = time.monotonic()
            first_chunk_at: float | None = None
            previous_chunk_at: float | None = None
            max_chunk_gap_ms = 0.0
            status = "success"
            response_id: str | None = None
            usage_received = False
            stream_failed = False
            try:
                with instrumented_span(
                    "llm.stream",
                    attributes={
                        "gen_ai.system": profile.provider,
                        "gen_ai.request.model": model,
                        "scholens.reasoning_level": reasoning_level.value,
                        "scholens.llm.streaming": True,
                    },
                ):
                    stream = self._client(reasoning_level).chat.completions.create(
                        model=model,
                        messages=messages,
                        stream=True,
                        stream_options={"include_usage": True},
                        extra_body=self._thinking_body(reasoning_level),
                        **kwargs,
                    )
                    close_provider = getattr(stream, "close", None)
                    if callable(close_provider):
                        cancellation.attach(close_provider)
                    if cancellation.cancelled:
                        status = "cancelled"
                        return
                    for chunk in stream:
                        response_id = getattr(chunk, "id", response_id)
                        if chunk.usage is not None:
                            usage_received = True
                            self._settle(
                                profile=profile,
                                response_id=response_id,
                                usage=chunk.usage,
                            )
                        if not chunk.choices:
                            continue
                        choice = chunk.choices[0]
                        text = choice.delta.content or ""
                        thinking = getattr(choice.delta, "reasoning_content", None)
                        if text or thinking or choice.finish_reason is not None:
                            chunk_at = time.monotonic()
                            if first_chunk_at is None:
                                first_chunk_at = chunk_at
                            if previous_chunk_at is not None:
                                max_chunk_gap_ms = max(
                                    max_chunk_gap_ms,
                                    (chunk_at - previous_chunk_at) * 1000,
                                )
                            previous_chunk_at = chunk_at
                            yield StreamChunk(
                                text=text,
                                is_done=choice.finish_reason is not None,
                                thinking=(
                                    thinking if isinstance(thinking, str) else None
                                ),
                            )
            except BaseException:
                status = "cancelled" if cancellation.cancelled else "failure"
                stream_failed = True
                raise
            finally:
                cancellation.detach()
                if not usage_received:
                    try:
                        self._settle(
                            profile=profile,
                            response_id=response_id,
                            usage=None,
                        )
                    except LLMUsageSettlementError:
                        if not stream_failed:
                            raise
                        logger.exception(
                            "llm.usage_settlement.failed_after_stream_error"
                        )
                attributes = {
                    "provider": profile.provider,
                    "model": model,
                    "ai_profile": profile.name.value,
                    "streaming": True,
                    "status": status,
                }
                add_counter("scholens.llm.requests", attributes=attributes)
                record_histogram(
                    "scholens.llm.duration",
                    (time.monotonic() - started) * 1000,
                    attributes=attributes,
                )
                logger.info(
                    "llm.request.completed",
                    extra={
                        **attributes,
                        "duration_ms": round(
                            (time.monotonic() - started) * 1000,
                            3,
                        ),
                    },
                )
                if first_chunk_at is not None:
                    record_histogram(
                        "scholens.llm.time_to_first_chunk",
                        (first_chunk_at - started) * 1000,
                        attributes={
                            "provider": profile.provider,
                            "model": model,
                            "ai_profile": profile.name.value,
                        },
                    )
                    record_histogram(
                        "scholens.llm.max_chunk_gap",
                        max_chunk_gap_ms,
                        attributes={
                            "provider": profile.provider,
                            "model": model,
                            "ai_profile": profile.name.value,
                        },
                    )

        return _CancellableIterator(stream_chunks)

    def _convert_message_content(self, content: MessageParam) -> Any:
        if isinstance(content, str):
            return content
        parts: list[dict[str, str]] = []
        for item in content:
            if isinstance(item, TextContent):
                parts.append({"type": "text", "text": item.text})
            elif isinstance(item, SupplementaryContent):
                parts.append(
                    {
                        "type": "text",
                        "text": f"<{item.label}>\n{item.content}\n</{item.label}>",
                    }
                )
            elif isinstance(item, FileContent):
                if item.text_fallback is None:
                    raise ValueError(
                        "FileContent.text_fallback is required by this chat adapter"
                    )
                filename = item.filename or "document.pdf"
                parts.append(
                    {
                        "type": "text",
                        "text": (
                            f'<document filename="{filename}">\n'
                            f"{item.text_fallback}\n</document>"
                        ),
                    }
                )
        return parts

    def _prepare_messages(
        self,
        history: Sequence[HistoryMessage],
        new_message: MessageParam,
        system_prompt: str = "",
        file: FileContent | None = None,
        tool_call_results: list[ToolCallResult] | None = None,
    ) -> list[ChatCompletionMessageParam]:
        messages: list[dict[str, Any]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        if file:
            messages.append(
                {"role": "user", "content": self._convert_message_content([file])}
            )
        for item in history:
            role = "assistant" if item.role == "assistant" else "user"
            messages.append({"role": role, "content": str(item.content)})
        if tool_call_results:
            calls = []
            for index, result in enumerate(tool_call_results):
                calls.append(
                    {
                        "id": result.id or f"call_{index}",
                        "type": "function",
                        "function": {
                            "name": result.name,
                            "arguments": json.dumps(result.args),
                        },
                    }
                )
            messages.append({"role": "assistant", "content": None, "tool_calls": calls})
            for index, result in enumerate(tool_call_results):
                value = result.result
                content = (
                    json.dumps(value, ensure_ascii=False)
                    if isinstance(value, (dict, list))
                    else str(value)
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": result.id or f"call_{index}",
                        "content": content,
                    }
                )
        messages.append(
            {"role": "user", "content": self._convert_message_content(new_message)}
        )
        return cast(list[ChatCompletionMessageParam], messages)

    def _cast_tool_declaration(
        self, declaration: dict[str, Any]
    ) -> ChatCompletionToolParam:
        return {
            "type": "function",
            "function": {
                "name": declaration["name"],
                "description": declaration.get("description", ""),
                "parameters": declaration.get("parameters", {}),
            },
        }


@lru_cache(maxsize=1)
def get_llm_backend() -> LLMBackend:
    """Return the process-wide backend and its reusable HTTP connection pool."""
    return ProfiledChatBackend()


__all__ = [
    "ProfiledChatBackend",
    "FileContent",
    "LLMResponse",
    "LLMBackend",
    "LLMUsageSettlementError",
    "MalformedToolCall",
    "MessageParam",
    "StreamChunk",
    "SupplementaryContent",
    "TextContent",
    "ToolCallResult",
    "get_llm_backend",
]
