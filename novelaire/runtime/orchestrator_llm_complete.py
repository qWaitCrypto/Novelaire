from __future__ import annotations

import time
from typing import Any

from .error_codes import ErrorCode
from .llm.errors import CancellationToken, LLMRequestError
from .llm.trace import LLMTrace
from .llm.types import CanonicalRequest, ModelRequirements, ModelRole
from .protocol import EventKind, OpKind
from .tools import PlannedToolCall
from .orchestrator_llm_common import _finalize_llm_response, _plan_tool_calls


def run_llm_complete(
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
        trace.record_meta(profile_id=profile_id, context_ref=context_ref, operation="complete")
    orch._emit(
        kind=EventKind.LLM_REQUEST_STARTED,
        payload={
            "role": ModelRole.MAIN.value,
            "context_ref": context_ref,
            "profile_id": profile_id,
            "timeout_s": timeout_s,
            "stream": False,
            "context_stats": dict(context_stats or {}),
        },
        request_id=request_id,
        turn_id=turn_id,
        step_id=step_id,
    )

    attempt = 1
    max_attempts = 2
    while True:
        try:
            final_response = orch.llm_client.complete(
                role=ModelRole.MAIN,
                requirements=ModelRequirements(needs_streaming=False, needs_tools=bool(request.tools)),
                request=request,
                timeout_s=timeout_s,
                cancel=cancel,
                trace=trace,
            )
            break
        except LLMRequestError as e:
            if trace is not None:
                if e.code is ErrorCode.CANCELLED:
                    trace.record_cancelled(reason="cancelled", code=ErrorCode.CANCELLED.value)
                else:
                    trace.record_error(e, code=e.code.value if e.code is not None else None)
                try:
                    trace.write_json(
                        f"complete_error_attempt_{attempt}.json",
                        {
                            "attempt": attempt,
                            "error": str(e),
                            "error_code": e.code.value if e.code is not None else None,
                            "provider_kind": e.provider_kind.value if e.provider_kind is not None else None,
                            "profile_id": e.profile_id,
                            "model": e.model,
                            "retryable": e.retryable,
                            "details": e.details,
                        },
                    )
                except Exception:
                    pass
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
                    "attempt": attempt,
                },
                request_id=request_id,
                turn_id=turn_id,
                step_id=step_id,
            )
            if e.code is ErrorCode.CANCELLED:
                orch._emit(
                    kind=EventKind.OPERATION_CANCELLED,
                    payload={
                        "op_kind": OpKind.CHAT.value,
                        "error_code": ErrorCode.CANCELLED.value,
                        "reason": "cancelled",
                        "phase": "llm_complete",
                    },
                    request_id=request_id,
                    turn_id=turn_id,
                    step_id=step_id,
                )
                return None, []

            can_retry = bool(e.retryable) and attempt < max_attempts and not cancel.cancelled
            if can_retry:
                attempt += 1
                orch._emit(
                    kind=EventKind.OPERATION_PROGRESS,
                    payload={
                        "op_kind": OpKind.CHAT.value,
                        "message": f"LLM request failed ({e.code.value}); retrying (attempt {attempt}/{max_attempts}).",
                        "error_code": e.code.value,
                        "phase": "llm_complete",
                    },
                    request_id=request_id,
                    turn_id=turn_id,
                    step_id=step_id,
                )
                orch._emit(
                    kind=EventKind.LLM_REQUEST_STARTED,
                    payload={
                        "role": ModelRole.MAIN.value,
                        "context_ref": context_ref,
                        "profile_id": profile_id,
                        "timeout_s": timeout_s,
                        "stream": False,
                        "context_stats": dict(context_stats or {}),
                        "attempt": attempt,
                    },
                    request_id=request_id,
                    turn_id=turn_id,
                    step_id=step_id,
                )
                time.sleep(0.25 * float(attempt))
                continue

            orch._emit(
                kind=EventKind.OPERATION_FAILED,
                payload={"error": str(e), "error_code": e.code.value, "type": "llm_request"},
                request_id=request_id,
                turn_id=turn_id,
                step_id=step_id,
            )
            return None, []

    assistant_text = final_response.text
    if assistant_text:
        orch._emit(
            kind=EventKind.LLM_RESPONSE_DELTA,
            payload={"text_delta": assistant_text},
            request_id=request_id,
            turn_id=turn_id,
            step_id=step_id,
        )

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
        extra_payload={"stream": False},
    )
    return final_response, planned_calls
