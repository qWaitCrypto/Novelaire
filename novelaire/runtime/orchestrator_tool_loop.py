from __future__ import annotations

from .approval import ApprovalRecord, ApprovalStatus
from .error_codes import ErrorCode
from .ids import new_id, now_ts_ms
from .llm.types import CanonicalMessage, CanonicalMessageRole
from .protocol import EventKind, OpKind
from .tools import InspectionDecision, PlannedToolCall, ToolRuntimeError
from .orchestrator_helpers import _planned_tool_call_descriptor, _summarize_tool_for_ui


def handle_planned_tool_calls(
    orch,
    *,
    planned_calls: list[PlannedToolCall],
    request_id: str,
    turn_id: str | None,
    timeout_s: float | None,
    skip_approval_tool_execution_id: str | None,
) -> bool:
    if orch.tool_runtime is None:
        raise RuntimeError("Tool runtime not initialized.")

    for idx, planned in enumerate(planned_calls):
        ui_summary = _summarize_tool_for_ui(planned.tool_name, planned.arguments)
        inspection = orch.tool_runtime.inspect(planned)
        if inspection.decision is InspectionDecision.DENY:
            code = inspection.error_code or ErrorCode.TOOL_DENIED
            orch._emit(
                kind=EventKind.TOOL_CALL_END,
                payload={
                    "tool_execution_id": planned.tool_execution_id,
                    "tool_name": planned.tool_name,
                    "tool_call_id": planned.tool_call_id,
                    "summary": ui_summary,
                    "status": "denied",
                    "error_code": code.value,
                    "error": inspection.reason or inspection.action_summary,
                },
                request_id=request_id,
                turn_id=turn_id,
                step_id=planned.tool_execution_id,
            )
            orch._emit(
                kind=EventKind.OPERATION_FAILED,
                payload={
                    "error": inspection.reason or inspection.action_summary,
                    "error_code": code.value,
                    "type": "tool_denied",
                },
                request_id=request_id,
                turn_id=turn_id,
                step_id=planned.tool_execution_id,
            )
            return False

        if (
            inspection.decision is InspectionDecision.REQUIRE_APPROVAL
            and planned.tool_execution_id != skip_approval_tool_execution_id
        ):
            approval_id = new_id("appr")
            remaining = planned_calls[idx:]
            record = ApprovalRecord(
                approval_id=approval_id,
                session_id=orch.session_id,
                request_id=request_id,
                created_at=now_ts_ms(),
                status=ApprovalStatus.PENDING,
                turn_id=turn_id,
                action_summary=inspection.action_summary,
                risk_level=inspection.risk_level or "high",
                options=["approve", "deny"],
                reason=inspection.reason,
                diff_ref=inspection.diff_ref.to_dict() if inspection.diff_ref is not None else None,
                resume_kind="tool_chain",
                resume_payload={
                    "tool_calls": [_planned_tool_call_descriptor(p) for p in remaining],
                },
            )
            orch.approval_store.create(record)
            orch._emit(
                kind=EventKind.APPROVAL_REQUIRED,
                payload={
                    "approval_id": approval_id,
                    "action_summary": record.action_summary,
                    "risk_level": record.risk_level,
                    "options": record.options,
                    "reason": record.reason,
                    "diff_ref": record.diff_ref,
                    "tool_execution_id": planned.tool_execution_id,
                    "tool_name": planned.tool_name,
                    "tool_call_id": planned.tool_call_id,
                    "summary": ui_summary,
                    "arguments_ref": planned.arguments_ref.to_dict(),
                },
                request_id=request_id,
                turn_id=turn_id,
                step_id=planned.tool_execution_id,
            )
            return False

        orch._emit(
            kind=EventKind.TOOL_CALL_START,
            payload={
                "tool_execution_id": planned.tool_execution_id,
                "tool_name": planned.tool_name,
                "tool_call_id": planned.tool_call_id,
                "summary": ui_summary,
                "arguments_ref": planned.arguments_ref.to_dict(),
            },
            request_id=request_id,
            turn_id=turn_id,
            step_id=planned.tool_execution_id,
        )
        try:
            result = orch.tool_runtime.execute(planned)
        except KeyboardInterrupt:
            orch._emit(
                kind=EventKind.TOOL_CALL_END,
                payload={
                    "tool_execution_id": planned.tool_execution_id,
                    "tool_name": planned.tool_name,
                    "tool_call_id": planned.tool_call_id,
                    "summary": ui_summary,
                    "status": "cancelled",
                    "duration_ms": 0,
                    "output_ref": None,
                    "tool_message_ref": None,
                    "error_code": ErrorCode.CANCELLED.value,
                    "error": "Cancelled by user.",
                },
                request_id=request_id,
                turn_id=turn_id,
                step_id=planned.tool_execution_id,
            )
            orch._emit(
                kind=EventKind.OPERATION_CANCELLED,
                payload={
                    "op_kind": OpKind.CHAT.value,
                    "error_code": ErrorCode.CANCELLED.value,
                    "reason": "user_interrupt",
                    "phase": "tool_execute",
                    "tool_execution_id": planned.tool_execution_id,
                    "tool_name": planned.tool_name,
                    "tool_call_id": planned.tool_call_id,
                },
                request_id=request_id,
                turn_id=turn_id,
                step_id=planned.tool_execution_id,
            )
            return False
        orch._emit(
            kind=EventKind.TOOL_CALL_END,
            payload={
                "tool_execution_id": result.tool_execution_id,
                "tool_name": result.tool_name,
                "tool_call_id": result.tool_call_id,
                "summary": ui_summary,
                "status": result.status,
                "duration_ms": result.duration_ms,
                "output_ref": result.output_ref.to_dict() if result.output_ref is not None else None,
                "tool_message_ref": result.tool_message_ref.to_dict() if result.tool_message_ref is not None else None,
                "error_code": (
                    result.error_code.value
                    if result.error_code is not None
                    else (None if result.status == "succeeded" else ErrorCode.TOOL_FAILED.value)
                ),
                "error": result.error,
            },
            request_id=request_id,
            turn_id=turn_id,
            step_id=planned.tool_execution_id,
        )

        if result.status == "succeeded" and result.tool_name == "update_plan" and orch.plan_store is not None:
            state = orch.plan_store.get()
            orch._emit(
                kind=EventKind.PLAN_UPDATE,
                payload={
                    "explanation": state.explanation,
                    "plan": [p.to_dict() for p in state.plan],
                    "updated_at": state.updated_at,
                },
                request_id=request_id,
                turn_id=turn_id,
                step_id=planned.tool_execution_id,
            )

        if result.status != "succeeded" or result.tool_message_content is None:
            op_code = result.error_code or ErrorCode.TOOL_FAILED
            orch._emit(
                kind=EventKind.OPERATION_FAILED,
                payload={
                    "error": result.error or "Tool failed.",
                    "error_code": op_code.value,
                    "type": "tool_failed",
                },
                request_id=request_id,
                turn_id=turn_id,
                step_id=planned.tool_execution_id,
            )
            return False

        if orch._history is None:
            orch._history = []
        orch._history.append(
            CanonicalMessage(
                role=CanonicalMessageRole.TOOL,
                content=result.tool_message_content,
                tool_call_id=planned.tool_call_id,
                tool_name=planned.tool_name,
            )
        )

    return True

