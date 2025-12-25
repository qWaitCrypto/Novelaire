from __future__ import annotations

import time
from typing import Any

from .error_codes import ErrorCode
from .llm.errors import CancellationToken, LLMRequestError, ModelResolutionError
from .llm.trace import LLMTrace
from .llm.types import CanonicalRequest, ModelRequirements, ModelRole
from .protocol import EventKind, OpKind
from .tools import PlannedToolCall
from .orchestrator_llm_common import _finalize_llm_response, _plan_tool_calls


def run_llm_stream(
    orch,
    *,
    request: CanonicalRequest,
    context_ref: dict[str, Any],
    context_stats: dict[str, Any] | None,
    profile_id: str,
    request_id: str,
    turn_id: str | None,
    step_id: str,
    timeout_s: float | None,
    cancel: CancellationToken | None,
) -> tuple[Any | None, list[PlannedToolCall]]:
    cancel = cancel or CancellationToken()
    trace = LLMTrace.maybe_create(
        project_root=orch.project_root,
        session_id=orch.session_id,
        request_id=request_id,
        turn_id=turn_id,
        step_id=step_id,
    )
    if trace is not None:
        trace.record_meta(profile_id=profile_id, context_ref=context_ref, operation="stream")
    stream_iter = None
    orch._emit(
        kind=EventKind.LLM_REQUEST_STARTED,
        payload={
            "role": ModelRole.MAIN.value,
            "context_ref": context_ref,
            "profile_id": profile_id,
            "timeout_s": timeout_s,
            "context_stats": dict(context_stats or {}),
        },
        request_id=request_id,
        turn_id=turn_id,
        step_id=step_id,
    )

    delta_buf: list[str] = []
    streamed_parts: list[str] = []
    final_response = None
    last_emit = time.monotonic()

    try:
        stream_iter = orch.llm_client.stream(
            role=ModelRole.MAIN,
            requirements=ModelRequirements(needs_streaming=True),
            request=request,
            timeout_s=timeout_s,
            cancel=cancel,
            trace=trace,
        )
        for ev in stream_iter:
            if ev.kind.value == "text_delta" and ev.text_delta is not None:
                delta_buf.append(ev.text_delta)
                now = time.monotonic()
                # Keep the UI responsive: flush frequently by time or size, not only on large chunks.
                if sum(len(p) for p in delta_buf) >= 32 or "\n" in ev.text_delta or (now - last_emit) >= 0.08:
                    emitted = "".join(delta_buf)
                    orch._emit(
                        kind=EventKind.LLM_RESPONSE_DELTA,
                        payload={"text_delta": emitted},
                        request_id=request_id,
                        turn_id=turn_id,
                        step_id=step_id,
                    )
                    streamed_parts.append(emitted)
                    delta_buf.clear()
                    last_emit = now
            elif ev.kind.value == "thinking_delta" and getattr(ev, "thinking_delta", None):
                orch._emit(
                    kind=EventKind.LLM_THINKING_DELTA,
                    payload={"thinking_delta": ev.thinking_delta},
                    request_id=request_id,
                    turn_id=turn_id,
                    step_id=step_id,
                )
            elif ev.kind.value == "completed" and ev.response is not None:
                final_response = ev.response
    except KeyboardInterrupt:
        cancel.cancel()
        if trace is not None:
            trace.record_cancelled(reason="user_interrupt", code=ErrorCode.CANCELLED.value)
        if stream_iter is not None:
            try:
                close = getattr(stream_iter, "close", None)
                if callable(close):
                    close()
            except Exception:
                pass
        if delta_buf:
            orch._emit(
                kind=EventKind.LLM_RESPONSE_DELTA,
                payload={"text_delta": "".join(delta_buf)},
                request_id=request_id,
                turn_id=turn_id,
                step_id=step_id,
            )
        orch._emit(
            kind=EventKind.OPERATION_CANCELLED,
            payload={
                "op_kind": OpKind.CHAT.value,
                "error_code": ErrorCode.CANCELLED.value,
                "reason": "user_interrupt",
                "phase": "llm_stream",
            },
            request_id=request_id,
            turn_id=turn_id,
            step_id=step_id,
        )
        return None, []
    except LLMRequestError as e:
        if e.code is ErrorCode.CANCELLED:
            if trace is not None:
                trace.record_cancelled(reason="cancelled", code=ErrorCode.CANCELLED.value)
            orch._emit(
                kind=EventKind.LLM_REQUEST_FAILED,
                payload={
                    "error": str(e),
                    "error_code": e.code.value,
                    "code": e.code.value if e.code is not None else None,
                    "provider_kind": e.provider_kind.value if e.provider_kind is not None else None,
                    "profile_id": e.profile_id,
                    "model": e.model,
                    "retryable": e.retryable,
                    "details": e.details,
                },
                request_id=request_id,
                turn_id=turn_id,
                step_id=step_id,
            )
            orch._emit(
                kind=EventKind.OPERATION_CANCELLED,
                payload={
                    "op_kind": OpKind.CHAT.value,
                    "error_code": ErrorCode.CANCELLED.value,
                    "reason": "cancelled",
                    "phase": "llm_stream",
                },
                request_id=request_id,
                turn_id=turn_id,
                step_id=step_id,
            )
            return None, []

        # Best-effort fallback: some OpenAI-compatible gateways claim streaming support
        # but frequently terminate the TLS connection (e.g. SSLEOFError) before the first chunk.
        # If we haven't emitted any output yet, retry once using non-streaming complete().
        if e.code is ErrorCode.NETWORK_ERROR and not streamed_parts and not delta_buf:
            if trace is not None:
                trace.write_json(
                    "stream_error.json",
                    {
                        "type": type(e).__name__,
                        "message": str(e),
                        "code": e.code.value if e.code is not None else None,
                        "details": e.details,
                    },
                )
                trace.record_meta(stream_fallback=True, stream_error_code=e.code.value)

            orch._emit(
                kind=EventKind.LLM_REQUEST_FAILED,
                payload={
                    "error": str(e),
                    "error_code": e.code.value,
                    "code": e.code.value if e.code is not None else None,
                    "provider_kind": e.provider_kind.value if e.provider_kind is not None else None,
                    "profile_id": e.profile_id,
                    "model": e.model,
                    "retryable": e.retryable,
                    "details": e.details,
                    "handled": "fallback_to_complete",
                },
                request_id=request_id,
                turn_id=turn_id,
                step_id=step_id,
            )
            orch._emit(
                kind=EventKind.OPERATION_PROGRESS,
                payload={"message": "Streaming failed; retrying without streaming."},
                request_id=request_id,
                turn_id=turn_id,
                step_id=step_id,
            )
            return orch._run_llm_complete(
                request=request,
                context_ref=context_ref,
                context_stats=context_stats,
                profile_id=profile_id,
                request_id=request_id,
                turn_id=turn_id,
                step_id=step_id,
                timeout_s=timeout_s,
                cancel=cancel,
            )

        if trace is not None:
            trace.record_error(e, code=e.code.value if e.code is not None else None)
        orch._emit(
            kind=EventKind.LLM_REQUEST_FAILED,
            payload={
                "error": str(e),
                "error_code": e.code.value,
                "code": e.code.value if e.code is not None else None,
                "provider_kind": e.provider_kind.value if e.provider_kind is not None else None,
                "profile_id": e.profile_id,
                "model": e.model,
                "retryable": e.retryable,
                "details": e.details,
            },
            request_id=request_id,
            turn_id=turn_id,
            step_id=step_id,
        )
        orch._emit(
            kind=EventKind.OPERATION_FAILED,
            payload={"error": str(e), "error_code": e.code.value, "type": "llm_request"},
            request_id=request_id,
            turn_id=turn_id,
            step_id=step_id,
        )
        return None, []
    except ModelResolutionError as e:
        if trace is not None:
            trace.record_error(e, code=ErrorCode.MODEL_RESOLUTION.value)
        orch._emit(
            kind=EventKind.MODEL_RESOLUTION_FAILED,
            payload={
                "role": ModelRole.MAIN.value,
                "error": str(e),
                "error_code": ErrorCode.MODEL_RESOLUTION.value,
                "details": getattr(e, "details", None),
            },
            request_id=request_id,
            turn_id=turn_id,
            step_id=step_id,
        )
        orch._emit(
            kind=EventKind.OPERATION_FAILED,
            payload={
                "error": str(e),
                "error_code": ErrorCode.MODEL_RESOLUTION.value,
                "type": "model_resolution",
            },
            request_id=request_id,
            turn_id=turn_id,
            step_id=step_id,
        )
        return None, []

    if delta_buf:
        emitted = "".join(delta_buf)
        orch._emit(
            kind=EventKind.LLM_RESPONSE_DELTA,
            payload={"text_delta": emitted},
            request_id=request_id,
            turn_id=turn_id,
            step_id=step_id,
        )
        streamed_parts.append(emitted)

    if final_response is None:
        if trace is not None:
            trace.record_error(
                RuntimeError("LLM stream ended without a completed response."), code=ErrorCode.RESPONSE_VALIDATION.value
            )
        orch._emit(
            kind=EventKind.OPERATION_FAILED,
            payload={
                "error": "LLM stream ended without a completed response.",
                "error_code": ErrorCode.RESPONSE_VALIDATION.value,
                "type": "llm_missing_completed",
            },
            request_id=request_id,
            turn_id=turn_id,
            step_id=step_id,
        )
        return None, []

    planned_calls = _plan_tool_calls(
        orch,
        tool_calls=final_response.tool_calls,
        request_id=request_id,
        turn_id=turn_id,
        step_id=step_id,
    )
    if planned_calls is None:
        return None, []

    _finalize_llm_response(
        orch,
        final_response=final_response,
        planned_calls=planned_calls,
        context_stats=context_stats,
        request_id=request_id,
        turn_id=turn_id,
        step_id=step_id,
        trace=trace,
    )
    return final_response, planned_calls

