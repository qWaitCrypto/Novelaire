from __future__ import annotations

import json
import threading
import time
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
    CredentialResolutionError,
    wrap_provider_exception,
)
from .providers.anthropic import AnthropicAdapter
from .providers.openai_compatible import OpenAICompatibleAdapter
from .router import ModelRouter
from .secrets import resolve_credential
from .trace import LLMTrace
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
    # Best-effort close: various SDKs wrap the underlying HTTP response object differently.
    close = getattr(stream, "close", None)
    if callable(close):
        close()
        return
    aclose = getattr(stream, "aclose", None)
    if callable(aclose):
        try:
            aclose()
        except Exception:
            pass
        return
    for attr in ("response", "_response", "http_response", "_http_response"):
        inner = getattr(stream, attr, None)
        if inner is None:
            continue
        close2 = getattr(inner, "close", None)
        if callable(close2):
            try:
                close2()
            except Exception:
                pass
            return


def _start_cancel_closer(cancel: CancellationToken | None, stream: Any) -> threading.Event | None:
    if cancel is None:
        return None
    stop = threading.Event()

    def _run() -> None:
        while not stop.is_set():
            if cancel.cancelled:
                try:
                    _maybe_close_stream(stream)
                except Exception:
                    pass
                return
            stop.wait(0.05)

    t = threading.Thread(target=_run, name="novelaire-llm-stream-cancel", daemon=True)
    t.start()
    return stop


def _start_stream_idle_watchdog(
    *,
    stream: Any,
    cancel: CancellationToken | None,
    first_event_timeout_s: float | None,
    idle_timeout_s: float | None,
) -> tuple[threading.Event, threading.Event, callable, callable]:
    """
    Best-effort guard for buggy "streaming" endpoints that never send a terminal event / never close.

    - `first_event_timeout_s`: max time waiting for the first stream item.
    - `idle_timeout_s`: max time between stream items after the first item.

    When triggered, calls `stream.close()` and sets `timed_out`.
    """
    stop = threading.Event()
    timed_out = threading.Event()
    lock = threading.Lock()
    last_progress = [time.monotonic()]
    saw_any = [False]
    phase: list[str | None] = [None]

    def tick() -> None:
        with lock:
            last_progress[0] = time.monotonic()
            saw_any[0] = True

    def timed_out_phase() -> str | None:
        with lock:
            return phase[0]

    def _run() -> None:
        started = time.monotonic()
        while not stop.is_set():
            if cancel is not None and cancel.cancelled:
                return
            now = time.monotonic()
            with lock:
                last = last_progress[0]
                any_seen = saw_any[0]
            if (not any_seen) and first_event_timeout_s is not None and (now - started) >= first_event_timeout_s:
                with lock:
                    phase[0] = "first_event"
                timed_out.set()
                try:
                    _maybe_close_stream(stream)
                except Exception:
                    pass
                return
            if any_seen and idle_timeout_s is not None and (now - last) >= idle_timeout_s:
                with lock:
                    phase[0] = "idle"
                timed_out.set()
                try:
                    _maybe_close_stream(stream)
                except Exception:
                    pass
                return
            stop.wait(0.05)

    t = threading.Thread(target=_run, name="novelaire-llm-stream-idle", daemon=True)
    t.start()
    return stop, timed_out, tick, timed_out_phase


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
            snippet = raw.replace("\r", "\\r").replace("\n", "\\n")
            if len(snippet) > 240:
                snippet = snippet[:240] + f"... (+{len(raw) - 240} chars)"
            raise ProviderAdapterError(
                f"OpenAI tool call '{self.name}' arguments are not valid JSON: {e}; raw={snippet!r}"
            ) from e
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
        trace: LLMTrace | None = None,
    ) -> LLMResponse:
        if requirements.needs_streaming:
            raise ProviderAdapterError("complete() does not support needs_streaming=True; use stream().")

        effective = _merge_requirements(requirements, request=request, force_streaming=False)
        resolved = self._router.resolve(role=role, requirements=effective)
        profile = resolved.profile
        if trace is not None:
            trace.record_canonical_request(request)
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
                raise LLMRequestError(
                    "Missing credentials for openai_compatible profile.",
                    code=LLMErrorCode.AUTH,
                    provider_kind=profile.provider_kind,
                    profile_id=profile.profile_id,
                    model=profile.model_name,
                    retryable=False,
                    details={"operation": "complete", "missing": "credential_ref"},
                )
            try:
                api_key = resolve_credential(profile.credential_ref)
            except CredentialResolutionError as e:
                raise LLMRequestError(
                    str(e),
                    code=LLMErrorCode.AUTH,
                    provider_kind=profile.provider_kind,
                    profile_id=profile.profile_id,
                    model=profile.model_name,
                    retryable=False,
                    details={"operation": "complete", "credential_ref": getattr(e, "credential_ref", None)},
                    cause=e,
                ) from e
            client = OpenAI(api_key=api_key, base_url=profile.base_url, max_retries=0)
            payload = OpenAICompatibleAdapter().prepare_request(profile, request).json
            request_timeout_s = timeout_s if timeout_s is not None else profile.timeout_s
            if trace is not None:
                trace.record_prepared_request(
                    provider_kind=profile.provider_kind,
                    profile_id=profile.profile_id,
                    base_url=profile.base_url,
                    model=profile.model_name,
                    stream=False,
                    timeout_s=request_timeout_s,
                    payload=payload,
                )
            try:
                if request_timeout_s is not None:
                    resp = client.chat.completions.create(**payload, timeout=request_timeout_s)
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
            except ProviderAdapterError as e:
                raise LLMRequestError(
                    str(e),
                    code=LLMErrorCode.BAD_REQUEST,
                    provider_kind=profile.provider_kind,
                    profile_id=profile.profile_id,
                    model=profile.model_name,
                    retryable=False,
                    details={"operation": "complete"},
                    cause=e,
                ) from e
            if trace is not None:
                trace.write_json("provider_response.json", resp)
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
                raise LLMRequestError(
                    "Missing credentials for anthropic profile.",
                    code=LLMErrorCode.AUTH,
                    provider_kind=profile.provider_kind,
                    profile_id=profile.profile_id,
                    model=profile.model_name,
                    retryable=False,
                    details={"operation": "complete", "missing": "credential_ref"},
                )
            try:
                api_key = resolve_credential(profile.credential_ref)
            except CredentialResolutionError as e:
                raise LLMRequestError(
                    str(e),
                    code=LLMErrorCode.AUTH,
                    provider_kind=profile.provider_kind,
                    profile_id=profile.profile_id,
                    model=profile.model_name,
                    retryable=False,
                    details={"operation": "complete", "credential_ref": getattr(e, "credential_ref", None)},
                    cause=e,
                ) from e
            client = Anthropic(api_key=api_key, base_url=profile.base_url, max_retries=0)
            payload = AnthropicAdapter().prepare_request(profile, request).json
            if "max_tokens" not in payload:
                raise ProviderAdapterError(
                    "Anthropic requests require 'max_tokens' (set in profile.default_params or request.params)."
                )
            request_timeout_s = timeout_s if timeout_s is not None else profile.timeout_s
            if trace is not None:
                trace.record_prepared_request(
                    provider_kind=profile.provider_kind,
                    profile_id=profile.profile_id,
                    base_url=profile.base_url,
                    model=profile.model_name,
                    stream=False,
                    timeout_s=request_timeout_s,
                    payload=payload,
                )
            try:
                if request_timeout_s is not None:
                    resp = client.messages.create(**payload, timeout=request_timeout_s)
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
            except ProviderAdapterError as e:
                raise LLMRequestError(
                    str(e),
                    code=LLMErrorCode.BAD_REQUEST,
                    provider_kind=profile.provider_kind,
                    profile_id=profile.profile_id,
                    model=profile.model_name,
                    retryable=False,
                    details={"operation": "complete"},
                    cause=e,
                ) from e
            if trace is not None:
                trace.write_json("provider_response.json", resp)
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
        trace: LLMTrace | None = None,
    ) -> Iterator[LLMStreamEvent]:
        effective = _merge_requirements(requirements, request=request, force_streaming=True)
        resolved = self._router.resolve(role=role, requirements=effective)
        profile = resolved.profile
        if trace is not None:
            trace.record_canonical_request(request)
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
                raise LLMRequestError(
                    "Missing credentials for openai_compatible profile.",
                    code=LLMErrorCode.AUTH,
                    provider_kind=profile.provider_kind,
                    profile_id=profile.profile_id,
                    model=profile.model_name,
                    retryable=False,
                    details={"operation": "stream", "missing": "credential_ref"},
                )
            try:
                api_key = resolve_credential(profile.credential_ref)
            except CredentialResolutionError as e:
                raise LLMRequestError(
                    str(e),
                    code=LLMErrorCode.AUTH,
                    provider_kind=profile.provider_kind,
                    profile_id=profile.profile_id,
                    model=profile.model_name,
                    retryable=False,
                    details={"operation": "stream", "credential_ref": getattr(e, "credential_ref", None)},
                    cause=e,
                ) from e
            client = OpenAI(api_key=api_key, base_url=profile.base_url, max_retries=0)
            payload = OpenAICompatibleAdapter().prepare_request(profile, request).json
            request_timeout_s = timeout_s if timeout_s is not None else profile.timeout_s
            if trace is not None:
                trace.record_prepared_request(
                    provider_kind=profile.provider_kind,
                    profile_id=profile.profile_id,
                    base_url=profile.base_url,
                    model=profile.model_name,
                    stream=True,
                    timeout_s=request_timeout_s,
                    payload=payload,
                )
            timeout_arg: Any | None = None
            if request_timeout_s is not None:
                # Some OpenAI-compatible gateways stall mid-stream. Keep the SDK's socket read
                # timeout aligned with the configured request timeout so users can tune it via
                # `NOVELAIRE_TIMEOUT_S` / `--timeout`.
                try:
                    import httpx  # type: ignore

                    read_timeout_s = float(request_timeout_s)
                    timeout_arg = httpx.Timeout(float(request_timeout_s), read=read_timeout_s)
                except Exception:
                    timeout_arg = float(request_timeout_s)
            try:
                if timeout_arg is not None:
                    raw_stream = client.chat.completions.create(
                        **payload, stream=True, timeout=timeout_arg
                    )
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
            except ProviderAdapterError as e:
                raise LLMRequestError(
                    str(e),
                    code=LLMErrorCode.BAD_REQUEST,
                    provider_kind=profile.provider_kind,
                    profile_id=profile.profile_id,
                    model=profile.model_name,
                    retryable=False,
                    details={"operation": "stream"},
                    cause=e,
                ) from e
    
            stop_closer = _start_cancel_closer(cancel, raw_stream)
            wd_stop, wd_timed_out, wd_tick, wd_phase = _start_stream_idle_watchdog(
                stream=raw_stream,
                cancel=cancel,
                first_event_timeout_s=(None if request_timeout_s is None else float(request_timeout_s)),
                # After the first chunk, token streams should stay "chatty". If we go silent,
                # close the stream so the CLI doesn't hang forever on buggy endpoints.
                idle_timeout_s=(None if request_timeout_s is None else float(request_timeout_s)),
            )
            try:
                for event in _openai_stream_to_events(
                    profile_id=profile.profile_id,
                    stream=raw_stream,
                    timeout_flag=wd_timed_out,
                    on_chunk=wd_tick,
                    on_provider_chunk=(None if trace is None else trace.record_provider_item),
                ):
                    _raise_if_cancelled(
                        cancel,
                        provider_kind=profile.provider_kind,
                        profile_id=profile.profile_id,
                        model=profile.model_name,
                        operation="stream",
                    )
                    if trace is not None:
                        trace.record_stream_event(event)
                    yield event
                if wd_timed_out.is_set():
                    phase = wd_phase()
                    raise LLMRequestError(
                        (
                            "Stream timed out waiting for first stream chunk."
                            if phase == "first_event"
                            else "Stream timed out (no terminal event / idle)."
                        ),
                        code=LLMErrorCode.TIMEOUT,
                        provider_kind=profile.provider_kind,
                        profile_id=profile.profile_id,
                        model=profile.model_name,
                        retryable=True,
                        details={"operation": "stream", "timeout_s": request_timeout_s, "phase": phase},
                    )
            except ProviderAdapterError as e:
                raise LLMRequestError(
                    str(e),
                    code=LLMErrorCode.RESPONSE_VALIDATION,
                    provider_kind=profile.provider_kind,
                    profile_id=profile.profile_id,
                    model=profile.model_name,
                    retryable=True,
                    details={"operation": "stream", "phase": "response_parse"},
                    cause=e,
                ) from e
            except openai.OpenAIError as e:
                if cancel is not None and cancel.cancelled:
                    raise LLMRequestError(
                        "Request cancelled.",
                        code=LLMErrorCode.CANCELLED,
                        provider_kind=profile.provider_kind,
                        profile_id=profile.profile_id,
                        model=profile.model_name,
                        retryable=False,
                        details={"operation": "stream"},
                        cause=e,
                    ) from e
                if wd_timed_out.is_set():
                    phase = wd_phase()
                    raise LLMRequestError(
                        (
                            "Stream timed out waiting for first stream chunk."
                            if phase == "first_event"
                            else "Stream timed out (no terminal event / idle)."
                        ),
                        code=LLMErrorCode.TIMEOUT,
                        provider_kind=profile.provider_kind,
                        profile_id=profile.profile_id,
                        model=profile.model_name,
                        retryable=True,
                        details={"operation": "stream", "timeout_s": request_timeout_s, "phase": phase},
                        cause=e,
                    ) from e
                raise wrap_provider_exception(
                    e,
                    provider_kind=profile.provider_kind,
                    profile_id=profile.profile_id,
                    model=profile.model_name,
                    operation="stream",
                ) from e
            finally:
                if stop_closer is not None:
                    stop_closer.set()
                wd_stop.set()
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
                raise LLMRequestError(
                    "Missing credentials for anthropic profile.",
                    code=LLMErrorCode.AUTH,
                    provider_kind=profile.provider_kind,
                    profile_id=profile.profile_id,
                    model=profile.model_name,
                    retryable=False,
                    details={"operation": "stream", "missing": "credential_ref"},
                )
            try:
                api_key = resolve_credential(profile.credential_ref)
            except CredentialResolutionError as e:
                raise LLMRequestError(
                    str(e),
                    code=LLMErrorCode.AUTH,
                    provider_kind=profile.provider_kind,
                    profile_id=profile.profile_id,
                    model=profile.model_name,
                    retryable=False,
                    details={"operation": "stream", "credential_ref": getattr(e, "credential_ref", None)},
                    cause=e,
                ) from e
            client = Anthropic(api_key=api_key, base_url=profile.base_url, max_retries=0)
            payload = AnthropicAdapter().prepare_request(profile, request).json
            if "max_tokens" not in payload:
                raise ProviderAdapterError(
                    "Anthropic requests require 'max_tokens' (set in profile.default_params or request.params)."
                )
            request_timeout_s = timeout_s if timeout_s is not None else profile.timeout_s
            if trace is not None:
                trace.record_prepared_request(
                    provider_kind=profile.provider_kind,
                    profile_id=profile.profile_id,
                    base_url=profile.base_url,
                    model=profile.model_name,
                    stream=True,
                    timeout_s=request_timeout_s,
                    payload=payload,
                )
            timeout_arg: Any | None = None
            if request_timeout_s is not None:
                try:
                    import httpx  # type: ignore

                    read_timeout_s = float(request_timeout_s)
                    timeout_arg = httpx.Timeout(float(request_timeout_s), read=read_timeout_s)
                except Exception:
                    timeout_arg = float(request_timeout_s)
            try:
                if timeout_arg is not None:
                    raw_stream = client.messages.create(**payload, stream=True, timeout=timeout_arg)
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
            except ProviderAdapterError as e:
                raise LLMRequestError(
                    str(e),
                    code=LLMErrorCode.BAD_REQUEST,
                    provider_kind=profile.provider_kind,
                    profile_id=profile.profile_id,
                    model=profile.model_name,
                    retryable=False,
                    details={"operation": "stream"},
                    cause=e,
                ) from e
    
            stop_closer = _start_cancel_closer(cancel, raw_stream)
            wd_stop, wd_timed_out, wd_tick, wd_phase = _start_stream_idle_watchdog(
                stream=raw_stream,
                cancel=cancel,
                first_event_timeout_s=(None if request_timeout_s is None else float(request_timeout_s)),
                idle_timeout_s=(None if request_timeout_s is None else float(request_timeout_s)),
            )
            try:
                for event in _anthropic_stream_to_events(
                    profile_id=profile.profile_id,
                    stream=raw_stream,
                    timeout_flag=wd_timed_out,
                    on_event=wd_tick,
                    on_provider_event=(None if trace is None else trace.record_provider_item),
                ):
                    _raise_if_cancelled(
                        cancel,
                        provider_kind=profile.provider_kind,
                        profile_id=profile.profile_id,
                        model=profile.model_name,
                        operation="stream",
                    )
                    if trace is not None:
                        trace.record_stream_event(event)
                    yield event
                if wd_timed_out.is_set():
                    phase = wd_phase()
                    raise LLMRequestError(
                        (
                            "Stream timed out waiting for first stream chunk."
                            if phase == "first_event"
                            else "Stream timed out (no terminal event / idle)."
                        ),
                        code=LLMErrorCode.TIMEOUT,
                        provider_kind=profile.provider_kind,
                        profile_id=profile.profile_id,
                        model=profile.model_name,
                        retryable=True,
                        details={"operation": "stream", "timeout_s": request_timeout_s, "phase": phase},
                    )
            except ProviderAdapterError as e:
                raise LLMRequestError(
                    str(e),
                    code=LLMErrorCode.RESPONSE_VALIDATION,
                    provider_kind=profile.provider_kind,
                    profile_id=profile.profile_id,
                    model=profile.model_name,
                    retryable=True,
                    details={"operation": "stream", "phase": "response_parse"},
                    cause=e,
                ) from e
            except anthropic.AnthropicError as e:
                if cancel is not None and cancel.cancelled:
                    raise LLMRequestError(
                        "Request cancelled.",
                        code=LLMErrorCode.CANCELLED,
                        provider_kind=profile.provider_kind,
                        profile_id=profile.profile_id,
                        model=profile.model_name,
                        retryable=False,
                        details={"operation": "stream"},
                        cause=e,
                    ) from e
                if wd_timed_out.is_set():
                    phase = wd_phase()
                    raise LLMRequestError(
                        (
                            "Stream timed out waiting for first stream chunk."
                            if phase == "first_event"
                            else "Stream timed out (no terminal event / idle)."
                        ),
                        code=LLMErrorCode.TIMEOUT,
                        provider_kind=profile.provider_kind,
                        profile_id=profile.profile_id,
                        model=profile.model_name,
                        retryable=True,
                        details={"operation": "stream", "timeout_s": request_timeout_s, "phase": phase},
                        cause=e,
                    ) from e
                raise wrap_provider_exception(
                    e,
                    provider_kind=profile.provider_kind,
                    profile_id=profile.profile_id,
                    model=profile.model_name,
                    operation="stream",
                ) from e
            finally:
                if stop_closer is not None:
                    stop_closer.set()
                wd_stop.set()
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


def _openai_stream_to_events(
    *,
    profile_id: str,
    stream: Any,
    timeout_flag: threading.Event | None = None,
    on_chunk: callable | None = None,
    on_provider_chunk: callable | None = None,
) -> Iterator[LLMStreamEvent]:
    text_parts: list[str] = []
    tool_builders: dict[int, _OpenAIToolCallBuilder] = {}
    stop_reason: str | None = None
    request_id: str | None = None
    model: str | None = None
    usage: LLMUsage | None = None

    try:
        for chunk in stream:
            if on_provider_chunk is not None:
                try:
                    on_provider_chunk(chunk)
                except Exception:
                    pass
            if on_chunk is not None:
                try:
                    on_chunk()
                except Exception:
                    pass
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

            # Some OpenAI-compatible gateways expose reasoning/thinking in a separate field.
            # Keep it out of final assistant text, but surface it as a thinking stream.
            reasoning_delta = getattr(delta, "reasoning_content", None)
            if reasoning_delta is None:
                reasoning_delta = getattr(delta, "reasoning", None)
            if reasoning_delta:
                yield LLMStreamEvent(kind=LLMStreamEventKind.THINKING_DELTA, thinking_delta=str(reasoning_delta))

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
    except Exception:
        # If we triggered an idle watchdog close, treat it as a terminal stream boundary
        # and still surface the partial response; the caller will turn this into TIMEOUT.
        if timeout_flag is None or not timeout_flag.is_set():
            raise

    if timeout_flag is not None and timeout_flag.is_set():
        return

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
        stop_reason=stop_reason or ("timeout" if (timeout_flag is not None and timeout_flag.is_set()) else None),
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


def _anthropic_stream_to_events(
    *,
    profile_id: str,
    stream: Any,
    timeout_flag: threading.Event | None = None,
    on_event: callable | None = None,
    on_provider_event: callable | None = None,
) -> Iterator[LLMStreamEvent]:
    text_parts: list[str] = []
    block_types: dict[int, str] = {}
    tool_builders: dict[int, _AnthropicToolCallBuilder] = {}
    tool_calls: list[ToolCall] = []
    stop_reason: str | None = None
    request_id: str | None = None
    model: str | None = None
    usage: LLMUsage | None = None

    try:
        for event in stream:
            if on_provider_event is not None:
                try:
                    on_provider_event(event)
                except Exception:
                    pass
            if on_event is not None:
                try:
                    on_event()
                except Exception:
                    pass

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
                if dtype == "thinking_delta":
                    thinking = getattr(delta, "thinking", None)
                    if thinking is None:
                        thinking = getattr(delta, "text", None)
                    if thinking:
                        yield LLMStreamEvent(kind=LLMStreamEventKind.THINKING_DELTA, thinking_delta=str(thinking))
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
    except Exception:
        if timeout_flag is None or not timeout_flag.is_set():
            raise

    if timeout_flag is not None and timeout_flag.is_set():
        return

    response = LLMResponse(
        provider_kind=ProviderKind.ANTHROPIC,
        profile_id=profile_id,
        model=model or "",
        text="".join(text_parts),
        tool_calls=tool_calls,
        usage=usage,
        stop_reason=stop_reason or ("timeout" if (timeout_flag is not None and timeout_flag.is_set()) else None),
        request_id=request_id,
    )
    yield LLMStreamEvent(kind=LLMStreamEventKind.COMPLETED, response=response)
