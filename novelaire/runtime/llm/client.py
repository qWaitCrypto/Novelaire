from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterator

import anthropic
import openai
from openai import OpenAI

from anthropic import Anthropic

from .config import ModelConfig
from .errors import (
    CancellationToken,
    LLMErrorCode,
    LLMRequestError,
    ProviderAdapterError,
    wrap_provider_exception,
)
from .providers.anthropic import AnthropicAdapter
from .providers.openai_compatible import OpenAICompatibleAdapter
from .router import ModelRouter
from .secrets import resolve_credential
from .types import (
    CanonicalRequest,
    LLMResponse,
    LLMStreamEvent,
    LLMStreamEventKind,
    LLMUsage,
    ModelRequirements,
    ModelRole,
    ProviderKind,
    ToolCall,
    ToolCallDelta,
)


def _merge_requirements(
    requirements: ModelRequirements, *, request: CanonicalRequest, force_streaming: bool
) -> ModelRequirements:
    return ModelRequirements(
        needs_streaming=force_streaming or requirements.needs_streaming,
        needs_tools=requirements.needs_tools or bool(request.tools),
        needs_structured_output=requirements.needs_structured_output,
        min_context_tokens=requirements.min_context_tokens,
    )


def _assert_no_reserved_params(
    *,
    profile_id: str,
    provider_kind: ProviderKind,
    profile_default_params: dict[str, Any],
    request_params: dict[str, Any],
    reserved_keys: set[str],
) -> None:
    found: set[str] = set()
    for k in reserved_keys:
        if k in profile_default_params or k in request_params:
            found.add(k)
    if found:
        rendered = ", ".join(sorted(found))
        raise ProviderAdapterError(
            f"Reserved params set in profile/request params for {provider_kind} profile '{profile_id}': {rendered}"
        )


def _raise_if_cancelled(
    cancel: CancellationToken | None,
    *,
    code: LLMErrorCode = LLMErrorCode.CANCELLED,
    provider_kind: ProviderKind,
    profile_id: str,
    model: str | None,
    operation: str,
) -> None:
    if cancel is not None and cancel.cancelled:
        raise LLMRequestError(
            "Request cancelled.",
            code=code,
            provider_kind=provider_kind,
            profile_id=profile_id,
            model=model,
            retryable=False,
            details={"operation": operation},
        )


def _maybe_close_stream(stream: Any) -> None:
    close = getattr(stream, "close", None)
    if callable(close):
        close()


@dataclass
class _OpenAIToolCallBuilder:
    tool_call_id: str | None = None
    name: str | None = None
    arguments_parts: list[str] | None = None

    def append_arguments(self, delta: str) -> None:
        if self.arguments_parts is None:
            self.arguments_parts = []
        self.arguments_parts.append(delta)

    def build(self) -> ToolCall:
        if not self.name:
            raise ProviderAdapterError("OpenAI tool call missing name.")
        raw = "".join(self.arguments_parts or [])
        try:
            parsed = json.loads(raw) if raw else {}
        except json.JSONDecodeError as e:
            raise ProviderAdapterError(f"OpenAI tool call arguments are not valid JSON: {e}") from e
        if not isinstance(parsed, dict):
            raise ProviderAdapterError("OpenAI tool call arguments must be a JSON object.")
        return ToolCall(tool_call_id=self.tool_call_id, name=self.name, arguments=parsed, raw_arguments=raw)


@dataclass
class _AnthropicToolCallBuilder:
    tool_call_id: str
    name: str
    partial_json_parts: list[str] | None = None

    def append_partial(self, delta: str) -> None:
        if self.partial_json_parts is None:
            self.partial_json_parts = []
        self.partial_json_parts.append(delta)

    def build(self) -> ToolCall:
        raw = "".join(self.partial_json_parts or [])
        if not raw:
            parsed: dict[str, Any] = {}
        else:
            try:
                parsed_any = json.loads(raw)
            except json.JSONDecodeError as e:
                raise ProviderAdapterError(
                    f"Anthropic tool_use input is not valid JSON: {e}"
                ) from e
            if not isinstance(parsed_any, dict):
                raise ProviderAdapterError("Anthropic tool_use input must be a JSON object.")
            parsed = parsed_any
        return ToolCall(tool_call_id=self.tool_call_id, name=self.name, arguments=parsed, raw_arguments=raw)


class LLMClient:
    def __init__(self, config: ModelConfig) -> None:
        self._router = ModelRouter(config)

    def complete(
        self,
        *,
        role: ModelRole,
        requirements: ModelRequirements,
        request: CanonicalRequest,
        timeout_s: float | None = None,
        cancel: CancellationToken | None = None,
    ) -> LLMResponse:
        if requirements.needs_streaming:
            raise ProviderAdapterError("complete() does not support needs_streaming=True; use stream().")

        effective = _merge_requirements(requirements, request=request, force_streaming=False)
        resolved = self._router.resolve(role=role, requirements=effective)
        profile = resolved.profile
        _raise_if_cancelled(
            cancel,
            provider_kind=profile.provider_kind,
            profile_id=profile.profile_id,
            model=profile.model_name,
            operation="complete",
        )

        if profile.provider_kind is ProviderKind.OPENAI_COMPATIBLE:
            _assert_no_reserved_params(
                profile_id=profile.profile_id,
                provider_kind=profile.provider_kind,
                profile_default_params=profile.default_params,
                request_params=request.params,
                reserved_keys={"model", "messages", "tools", "stream", "timeout"},
            )
            if profile.credential_ref is None:
                raise ProviderAdapterError("Missing credential_ref for openai_compatible profile.")
            api_key = resolve_credential(profile.credential_ref)
            client = OpenAI(api_key=api_key, base_url=profile.base_url, max_retries=0)
            payload = OpenAICompatibleAdapter().prepare_request(profile, request).json
            try:
                if timeout_s is not None:
                    resp = client.chat.completions.create(**payload, timeout=timeout_s)
                else:
                    resp = client.chat.completions.create(**payload)
            except openai.OpenAIError as e:
                raise wrap_provider_exception(
                    e,
                    provider_kind=profile.provider_kind,
                    profile_id=profile.profile_id,
                    model=profile.model_name,
                    operation="complete",
                ) from e
            return _openai_to_response(profile_id=profile.profile_id, resp=resp)

        if profile.provider_kind is ProviderKind.ANTHROPIC:
            _assert_no_reserved_params(
                profile_id=profile.profile_id,
                provider_kind=profile.provider_kind,
                profile_default_params=profile.default_params,
                request_params=request.params,
                reserved_keys={"model", "messages", "tools", "system", "stream", "timeout"},
            )
            if profile.credential_ref is None:
                raise ProviderAdapterError("Missing credential_ref for anthropic profile.")
            api_key = resolve_credential(profile.credential_ref)
            client = Anthropic(api_key=api_key, base_url=profile.base_url, max_retries=0)
            payload = AnthropicAdapter().prepare_request(profile, request).json
            if "max_tokens" not in payload:
                raise ProviderAdapterError(
                    "Anthropic requests require 'max_tokens' (set in profile.default_params or request.params)."
                )
            try:
                if timeout_s is not None:
                    resp = client.messages.create(**payload, timeout=timeout_s)
                else:
                    resp = client.messages.create(**payload)
            except anthropic.AnthropicError as e:
                raise wrap_provider_exception(
                    e,
                    provider_kind=profile.provider_kind,
                    profile_id=profile.profile_id,
                    model=profile.model_name,
                    operation="complete",
                ) from e
            return _anthropic_to_response(profile_id=profile.profile_id, resp=resp)

        raise ProviderAdapterError(f"Unsupported provider_kind: {profile.provider_kind}")

    def stream(
        self,
        *,
        role: ModelRole,
        requirements: ModelRequirements,
        request: CanonicalRequest,
        timeout_s: float | None = None,
        cancel: CancellationToken | None = None,
    ) -> Iterator[LLMStreamEvent]:
        effective = _merge_requirements(requirements, request=request, force_streaming=True)
        resolved = self._router.resolve(role=role, requirements=effective)
        profile = resolved.profile
        _raise_if_cancelled(
            cancel,
            provider_kind=profile.provider_kind,
            profile_id=profile.profile_id,
            model=profile.model_name,
            operation="stream",
        )

        if profile.provider_kind is ProviderKind.OPENAI_COMPATIBLE:
            _assert_no_reserved_params(
                profile_id=profile.profile_id,
                provider_kind=profile.provider_kind,
                profile_default_params=profile.default_params,
                request_params=request.params,
                reserved_keys={"model", "messages", "tools", "stream", "timeout"},
            )
            if profile.credential_ref is None:
                raise ProviderAdapterError("Missing credential_ref for openai_compatible profile.")
            api_key = resolve_credential(profile.credential_ref)
            client = OpenAI(api_key=api_key, base_url=profile.base_url, max_retries=0)
            payload = OpenAICompatibleAdapter().prepare_request(profile, request).json
            try:
                if timeout_s is not None:
                    raw_stream = client.chat.completions.create(**payload, stream=True, timeout=timeout_s)
                else:
                    raw_stream = client.chat.completions.create(**payload, stream=True)
            except openai.OpenAIError as e:
                raise wrap_provider_exception(
                    e,
                    provider_kind=profile.provider_kind,
                    profile_id=profile.profile_id,
                    model=profile.model_name,
                    operation="stream",
                ) from e

            try:
                for event in _openai_stream_to_events(profile_id=profile.profile_id, stream=raw_stream):
                    _raise_if_cancelled(
                        cancel,
                        provider_kind=profile.provider_kind,
                        profile_id=profile.profile_id,
                        model=profile.model_name,
                        operation="stream",
                    )
                    yield event
            except openai.OpenAIError as e:
                raise wrap_provider_exception(
                    e,
                    provider_kind=profile.provider_kind,
                    profile_id=profile.profile_id,
                    model=profile.model_name,
                    operation="stream",
                ) from e
            finally:
                _maybe_close_stream(raw_stream)
            return

        if profile.provider_kind is ProviderKind.ANTHROPIC:
            _assert_no_reserved_params(
                profile_id=profile.profile_id,
                provider_kind=profile.provider_kind,
                profile_default_params=profile.default_params,
                request_params=request.params,
                reserved_keys={"model", "messages", "tools", "system", "stream", "timeout"},
            )
            if profile.credential_ref is None:
                raise ProviderAdapterError("Missing credential_ref for anthropic profile.")
            api_key = resolve_credential(profile.credential_ref)
            client = Anthropic(api_key=api_key, base_url=profile.base_url, max_retries=0)
            payload = AnthropicAdapter().prepare_request(profile, request).json
            if "max_tokens" not in payload:
                raise ProviderAdapterError(
                    "Anthropic requests require 'max_tokens' (set in profile.default_params or request.params)."
                )
            try:
                if timeout_s is not None:
                    raw_stream = client.messages.create(**payload, stream=True, timeout=timeout_s)
                else:
                    raw_stream = client.messages.create(**payload, stream=True)
            except anthropic.AnthropicError as e:
                raise wrap_provider_exception(
                    e,
                    provider_kind=profile.provider_kind,
                    profile_id=profile.profile_id,
                    model=profile.model_name,
                    operation="stream",
                ) from e

            try:
                for event in _anthropic_stream_to_events(profile_id=profile.profile_id, stream=raw_stream):
                    _raise_if_cancelled(
                        cancel,
                        provider_kind=profile.provider_kind,
                        profile_id=profile.profile_id,
                        model=profile.model_name,
                        operation="stream",
                    )
                    yield event
            except anthropic.AnthropicError as e:
                raise wrap_provider_exception(
                    e,
                    provider_kind=profile.provider_kind,
                    profile_id=profile.profile_id,
                    model=profile.model_name,
                    operation="stream",
                ) from e
            finally:
                _maybe_close_stream(raw_stream)
            return

        raise ProviderAdapterError(f"Unsupported provider_kind: {profile.provider_kind}")


def _openai_to_usage(resp: Any) -> LLMUsage | None:
    usage = getattr(resp, "usage", None)
    if usage is None:
        return None
    prompt = getattr(usage, "prompt_tokens", None)
    completion = getattr(usage, "completion_tokens", None)
    total = getattr(usage, "total_tokens", None)
    return LLMUsage(input_tokens=prompt, output_tokens=completion, total_tokens=total)


def _openai_to_response(*, profile_id: str, resp: Any) -> LLMResponse:
    choice0 = resp.choices[0]
    msg = choice0.message
    tool_calls: list[ToolCall] = []
    if getattr(msg, "tool_calls", None):
        for tc in msg.tool_calls:
            raw_args = tc.function.arguments or ""
            try:
                parsed_any = json.loads(raw_args) if raw_args else {}
            except json.JSONDecodeError as e:
                raise ProviderAdapterError(f"OpenAI tool call arguments are not valid JSON: {e}") from e
            if not isinstance(parsed_any, dict):
                raise ProviderAdapterError("OpenAI tool call arguments must be a JSON object.")
            tool_calls.append(
                ToolCall(
                    tool_call_id=getattr(tc, "id", None),
                    name=tc.function.name,
                    arguments=parsed_any,
                    raw_arguments=raw_args,
                )
            )
    return LLMResponse(
        provider_kind=ProviderKind.OPENAI_COMPATIBLE,
        profile_id=profile_id,
        model=getattr(resp, "model", ""),
        text=getattr(msg, "content", None) or "",
        tool_calls=tool_calls,
        usage=_openai_to_usage(resp),
        stop_reason=getattr(choice0, "finish_reason", None),
        request_id=getattr(resp, "id", None),
    )


def _openai_stream_to_events(*, profile_id: str, stream: Any) -> Iterator[LLMStreamEvent]:
    text_parts: list[str] = []
    tool_builders: dict[int, _OpenAIToolCallBuilder] = {}
    stop_reason: str | None = None
    request_id: str | None = None
    model: str | None = None
    usage: LLMUsage | None = None

    for chunk in stream:
        if request_id is None:
            request_id = getattr(chunk, "id", None)
        if model is None:
            model = getattr(chunk, "model", None)
        if getattr(chunk, "usage", None) is not None:
            usage = _openai_to_usage(chunk)

        if not chunk.choices:
            continue
        choice0 = chunk.choices[0]
        delta = choice0.delta

        if getattr(choice0, "finish_reason", None) is not None:
            stop_reason = choice0.finish_reason

        content_delta = getattr(delta, "content", None)
        if content_delta:
            text_parts.append(content_delta)
            yield LLMStreamEvent(kind=LLMStreamEventKind.TEXT_DELTA, text_delta=content_delta)

        tool_deltas = getattr(delta, "tool_calls", None)
        if tool_deltas:
            for tc_delta in tool_deltas:
                idx = tc_delta.index
                builder = tool_builders.get(idx)
                if builder is None:
                    builder = _OpenAIToolCallBuilder()
                    tool_builders[idx] = builder
                if getattr(tc_delta, "id", None):
                    builder.tool_call_id = tc_delta.id
                if getattr(tc_delta, "function", None) is not None:
                    fn = tc_delta.function
                    if getattr(fn, "name", None):
                        builder.name = fn.name
                    if getattr(fn, "arguments", None):
                        builder.append_arguments(fn.arguments)
                        yield LLMStreamEvent(
                            kind=LLMStreamEventKind.TOOL_CALL_DELTA,
                            tool_call_delta=ToolCallDelta(
                                tool_call_index=idx,
                                tool_call_id=builder.tool_call_id,
                                name=builder.name,
                                raw_arguments_delta=fn.arguments,
                            ),
                        )

    tool_calls = [tool_builders[i].build() for i in sorted(tool_builders)]
    for call in tool_calls:
        yield LLMStreamEvent(kind=LLMStreamEventKind.TOOL_CALL, tool_call=call)
    response = LLMResponse(
        provider_kind=ProviderKind.OPENAI_COMPATIBLE,
        profile_id=profile_id,
        model=model or "",
        text="".join(text_parts),
        tool_calls=tool_calls,
        usage=usage,
        stop_reason=stop_reason,
        request_id=request_id,
    )
    yield LLMStreamEvent(kind=LLMStreamEventKind.COMPLETED, response=response)


def _anthropic_to_usage(resp: Any) -> LLMUsage | None:
    usage = getattr(resp, "usage", None)
    if usage is None:
        return None
    input_tokens = getattr(usage, "input_tokens", None)
    output_tokens = getattr(usage, "output_tokens", None)
    cache_creation = getattr(usage, "cache_creation_input_tokens", None)
    cache_read = getattr(usage, "cache_read_input_tokens", None)
    total = None
    if input_tokens is not None and output_tokens is not None:
        total = input_tokens + output_tokens
    return LLMUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total,
        cache_creation_input_tokens=cache_creation,
        cache_read_input_tokens=cache_read,
    )


def _anthropic_to_response(*, profile_id: str, resp: Any) -> LLMResponse:
    text_parts: list[str] = []
    tool_calls: list[ToolCall] = []

    for block in resp.content:
        if getattr(block, "type", None) == "text":
            text_parts.append(block.text)
        elif getattr(block, "type", None) == "tool_use":
            tool_calls.append(
                ToolCall(
                    tool_call_id=block.id,
                    name=block.name,
                    arguments=block.input,
                    raw_arguments=None,
                )
            )
        else:
            raise ProviderAdapterError(f"Unsupported Anthropic content block type: {getattr(block, 'type', None)}")

    return LLMResponse(
        provider_kind=ProviderKind.ANTHROPIC,
        profile_id=profile_id,
        model=getattr(resp, "model", ""),
        text="".join(text_parts),
        tool_calls=tool_calls,
        usage=_anthropic_to_usage(resp),
        stop_reason=str(getattr(resp, "stop_reason", None)) if getattr(resp, "stop_reason", None) else None,
        request_id=getattr(resp, "id", None),
    )


def _anthropic_stream_to_events(*, profile_id: str, stream: Any) -> Iterator[LLMStreamEvent]:
    text_parts: list[str] = []
    block_types: dict[int, str] = {}
    tool_builders: dict[int, _AnthropicToolCallBuilder] = {}
    tool_calls: list[ToolCall] = []
    stop_reason: str | None = None
    request_id: str | None = None
    model: str | None = None
    usage: LLMUsage | None = None

    for event in stream:
        etype = getattr(event, "type", None)
        if etype == "message_start":
            msg = event.message
            request_id = getattr(msg, "id", request_id)
            model = getattr(msg, "model", model)
            continue

        if etype == "content_block_start":
            idx = event.index
            block = event.content_block
            btype = getattr(block, "type", None)
            block_types[idx] = btype
            if btype == "tool_use":
                tool_builders[idx] = _AnthropicToolCallBuilder(tool_call_id=block.id, name=block.name)
            continue

        if etype == "content_block_delta":
            idx = event.index
            delta = event.delta
            dtype = getattr(delta, "type", None)
            if dtype == "text_delta":
                text = delta.text
                text_parts.append(text)
                yield LLMStreamEvent(kind=LLMStreamEventKind.TEXT_DELTA, text_delta=text)
                continue
            if dtype == "input_json_delta":
                builder = tool_builders.get(idx)
                if builder is None:
                    raise ProviderAdapterError("Anthropic input_json_delta without tool_use block start.")
                builder.append_partial(delta.partial_json)
                yield LLMStreamEvent(
                    kind=LLMStreamEventKind.TOOL_CALL_DELTA,
                    tool_call_delta=ToolCallDelta(
                        tool_call_index=idx,
                        tool_call_id=builder.tool_call_id,
                        name=builder.name,
                        raw_arguments_delta=delta.partial_json,
                    ),
                )
                continue
            raise ProviderAdapterError(f"Unsupported Anthropic content delta type: {dtype}")

        if etype == "content_block_stop":
            idx = event.index
            btype = block_types.get(idx)
            if btype == "tool_use":
                builder = tool_builders.get(idx)
                if builder is None:
                    raise ProviderAdapterError("Anthropic tool_use block stop without builder.")
                call = builder.build()
                tool_calls.append(call)
                yield LLMStreamEvent(kind=LLMStreamEventKind.TOOL_CALL, tool_call=call)
            continue

        if etype == "message_delta":
            if getattr(event, "usage", None) is not None:
                usage = _anthropic_to_usage(event)
            if getattr(event, "delta", None) is not None and getattr(event.delta, "stop_reason", None):
                stop_reason = str(event.delta.stop_reason)
            continue

        if etype == "message_stop":
            break

        raise ProviderAdapterError(f"Unsupported Anthropic stream event type: {etype}")

    response = LLMResponse(
        provider_kind=ProviderKind.ANTHROPIC,
        profile_id=profile_id,
        model=model or "",
        text="".join(text_parts),
        tool_calls=tool_calls,
        usage=usage,
        stop_reason=stop_reason,
        request_id=request_id,
    )
    yield LLMStreamEvent(kind=LLMStreamEventKind.COMPLETED, response=response)
