from __future__ import annotations

from typing import Any

from .context_mgmt import compute_context_left_percent
from .error_codes import ErrorCode
from .ids import new_id
from .llm.trace import LLMTrace
from .protocol import EventKind
from .tools import PlannedToolCall, ToolRuntimeError
from .orchestrator_helpers import _planned_tool_call_descriptor, _summarize_text


def _plan_tool_calls(
    orch,
    *,
    tool_calls: list[Any] | None,
    request_id: str,
    turn_id: str | None,
    step_id: str,
) -> list[PlannedToolCall] | None:
    planned_calls: list[PlannedToolCall] = []
    if not tool_calls:
        return planned_calls
    if orch.tool_runtime is None:
        raise RuntimeError("Tool runtime not initialized.")
    try:
        for call in tool_calls:
            planned_calls.append(
                orch.tool_runtime.plan(
                    tool_execution_id=new_id("tool"),
                    tool_name=call.name,
                    tool_call_id=call.tool_call_id or "",
                    arguments=call.arguments,
                )
            )
    except ToolRuntimeError as e:
        orch._emit(
            kind=EventKind.OPERATION_FAILED,
            payload={
                "error": str(e),
                "error_code": ErrorCode.TOOL_CALL_PLAN_FAILED.value,
                "type": "tool_call_plan_failed",
            },
            request_id=request_id,
            turn_id=turn_id,
            step_id=step_id,
        )
        return None
    return planned_calls


def _finalize_llm_response(
    orch,
    *,
    final_response: Any,
    planned_calls: list[PlannedToolCall],
    context_stats: dict[str, Any] | None,
    request_id: str,
    turn_id: str | None,
    step_id: str,
    trace: LLMTrace | None,
    extra_payload: dict[str, Any] | None = None,
) -> None:
    usage = final_response.usage.__dict__ if final_response.usage is not None else None
    merged_stats: dict[str, Any] = dict(context_stats or {})
    used_tokens = None
    if isinstance(usage, dict) and isinstance(usage.get("input_tokens"), int):
        used_tokens = int(usage["input_tokens"])
        merged_stats["input_tokens"] = used_tokens
        merged_stats["usage_source"] = "provider"
    elif isinstance(merged_stats.get("estimated_input_tokens"), int):
        used_tokens = int(merged_stats["estimated_input_tokens"])
        merged_stats["usage_source"] = "estimate"
    if isinstance(merged_stats.get("context_limit_tokens"), int) and isinstance(used_tokens, int):
        merged_stats["context_left_percent"] = compute_context_left_percent(
            used_tokens=used_tokens,
            context_limit_tokens=int(merged_stats["context_limit_tokens"]),
        )

    assistant_text = final_response.text
    output_ref = orch.artifact_store.put(
        assistant_text,
        kind="chat_assistant",
        meta={"summary": _summarize_text(assistant_text)},
    )
    payload: dict[str, Any] = {
        "profile_id": final_response.profile_id,
        "provider_kind": final_response.provider_kind.value,
        "model": final_response.model,
        "output_ref": output_ref.to_dict(),
        "tool_calls": [_planned_tool_call_descriptor(p) for p in planned_calls],
        "usage": usage,
        "context_stats": merged_stats,
        "stop_reason": final_response.stop_reason,
    }
    if isinstance(extra_payload, dict):
        payload.update(extra_payload)
    orch._emit(
        kind=EventKind.LLM_RESPONSE_COMPLETED,
        payload=payload,
        request_id=request_id,
        turn_id=turn_id,
        step_id=step_id,
    )

    if isinstance(usage, dict):
        try:
            orch.session_store.update_session(
                orch.session_id,
                {
                    "last_usage": usage,
                    "last_context_stats": merged_stats,
                },
            )
        except Exception:
            pass

    if trace is not None:
        trace.record_response(final_response)

