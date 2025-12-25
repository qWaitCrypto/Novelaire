from __future__ import annotations

from dataclasses import replace

from .approval import ApprovalDecision, ApprovalRecord, ApprovalStatus
from .error_codes import ErrorCode
from .ids import now_ts_ms
from .protocol import EventKind, Op, OpKind
from .orchestrator_helpers import (
    _planned_tool_call_descriptor,
    _planned_tool_call_from_descriptor,
    _summarize_tool_for_ui,
)


def handle_approval_decision(orch, op: Op, *, timeout_s: float | None) -> None:
    orch._emit(
        kind=EventKind.OPERATION_STARTED,
        payload={"op_kind": OpKind.APPROVAL_DECISION.value},
        request_id=op.request_id,
        turn_id=op.turn_id,
    )

    approval_id = str(op.payload.get("approval_id") or "")
    decision_raw = str(op.payload.get("decision") or "")
    note = op.payload.get("note")

    if not approval_id:
        orch._emit(
            kind=EventKind.OPERATION_FAILED,
            payload={
                "error": "Missing approval_id.",
                "error_code": ErrorCode.BAD_REQUEST.value,
                "type": "approval_decision",
            },
            request_id=op.request_id,
            turn_id=op.turn_id,
        )
        return

    try:
        record = orch.approval_store.get(approval_id)
    except FileNotFoundError:
        orch._emit(
            kind=EventKind.OPERATION_FAILED,
            payload={
                "error": f"Approval not found: {approval_id}",
                "error_code": ErrorCode.APPROVAL_NOT_FOUND.value,
                "type": "approval_decision",
            },
            request_id=op.request_id,
            turn_id=op.turn_id,
        )
        return

    if record.session_id != orch.session_id:
        orch._emit(
            kind=EventKind.OPERATION_FAILED,
            payload={
                "error": "Approval session mismatch.",
                "error_code": ErrorCode.APPROVAL_SESSION_MISMATCH.value,
                "type": "approval_decision",
            },
            request_id=op.request_id,
            turn_id=op.turn_id,
        )
        return

    if record.status is not ApprovalStatus.PENDING:
        orch._emit(
            kind=EventKind.OPERATION_FAILED,
            payload={
                "error": "Approval is not pending.",
                "error_code": ErrorCode.APPROVAL_NOT_PENDING.value,
                "type": "approval_decision",
                "status": record.status.value,
            },
            request_id=op.request_id,
            turn_id=op.turn_id,
        )
        return

    try:
        decision = ApprovalDecision(decision_raw)
    except ValueError:
        orch._emit(
            kind=EventKind.OPERATION_FAILED,
            payload={
                "error": f"Unsupported decision: {decision_raw!r}. Expected 'approve' or 'deny'.",
                "error_code": ErrorCode.APPROVAL_DECISION_INVALID.value,
                "type": "approval_decision",
            },
            request_id=op.request_id,
            turn_id=op.turn_id,
        )
        return

    decided_at = now_ts_ms()
    decision_obj = {
        "decision": decision.value,
        "note": str(note) if note is not None else None,
        "decided_at": decided_at,
        "decision_request_id": op.request_id,
    }

    if decision is ApprovalDecision.APPROVE:
        updated = replace(
            record,
            status=ApprovalStatus.GRANTED,
            decision=decision_obj,
        )
        orch.approval_store.update(updated)
        orch._emit(
            kind=EventKind.APPROVAL_GRANTED,
            payload={"approval_id": approval_id, "decision": decision_obj},
            request_id=record.request_id,
            turn_id=record.turn_id,
        )
        orch._emit(
            kind=EventKind.OPERATION_COMPLETED,
            payload={"op_kind": OpKind.APPROVAL_DECISION.value, "approval_id": approval_id},
            request_id=op.request_id,
            turn_id=op.turn_id,
        )
        resume_from_approval(orch, updated, timeout_s=timeout_s)
        return

    if decision is ApprovalDecision.DENY:
        updated = replace(
            record,
            status=ApprovalStatus.DENIED,
            decision=decision_obj,
        )
        orch.approval_store.update(updated)
        orch._emit(
            kind=EventKind.APPROVAL_DENIED,
            payload={"approval_id": approval_id, "decision": decision_obj},
            request_id=record.request_id,
            turn_id=record.turn_id,
        )
        if record.resume_kind == "tool_chain":
            raw_calls = record.resume_payload.get("tool_calls")
            if isinstance(raw_calls, list) and raw_calls and isinstance(raw_calls[0], dict):
                first = raw_calls[0]
                tool_execution_id = first.get("tool_execution_id")
                tool_name = first.get("tool_name")
                tool_call_id = first.get("tool_call_id")
                summary = None
                try:
                    planned = _planned_tool_call_from_descriptor(first, read_artifact_text=orch._read_artifact_text)
                    summary = _summarize_tool_for_ui(planned.tool_name, planned.arguments)
                except Exception:
                    summary = None
                if (
                    isinstance(tool_execution_id, str)
                    and tool_execution_id
                    and isinstance(tool_name, str)
                    and tool_name
                    and isinstance(tool_call_id, str)
                    and tool_call_id
                ):
                    orch._emit(
                        kind=EventKind.TOOL_CALL_END,
                        payload={
                            "tool_execution_id": tool_execution_id,
                            "tool_name": tool_name,
                            "tool_call_id": tool_call_id,
                            "summary": summary,
                            "status": "cancelled",
                            "error_code": ErrorCode.CANCELLED.value,
                            "error": "Approval denied.",
                        },
                        request_id=record.request_id,
                        turn_id=record.turn_id,
                    )
        orch._emit(
            kind=EventKind.OPERATION_CANCELLED,
            payload={
                "op_kind": OpKind.CHAT.value,
                "approval_id": approval_id,
                "error_code": ErrorCode.CANCELLED.value,
            },
            request_id=record.request_id,
            turn_id=record.turn_id,
        )
        orch._emit(
            kind=EventKind.OPERATION_COMPLETED,
            payload={"op_kind": OpKind.APPROVAL_DECISION.value, "approval_id": approval_id},
            request_id=op.request_id,
            turn_id=op.turn_id,
        )
        return

    orch._emit(
        kind=EventKind.OPERATION_FAILED,
        payload={
            "error": f"Decision not supported yet: {decision.value}",
            "error_code": ErrorCode.APPROVAL_DECISION_INVALID.value,
            "type": "approval_decision",
        },
        request_id=op.request_id,
        turn_id=op.turn_id,
    )


def resume_from_approval(orch, record: ApprovalRecord, *, timeout_s: float | None) -> None:
    if record.resume_kind in ("chat_continue", "chat_llm"):
        orch._continue_chat_operation(
            request_id=record.request_id,
            turn_id=record.turn_id,
            timeout_s=timeout_s,
            cancel=None,
        )
        return

    if record.resume_kind == "tool_chain":
        resume_tool_chain(orch, record, timeout_s=timeout_s)
        return

    orch._emit(
        kind=EventKind.OPERATION_FAILED,
        payload={
            "error": f"Unsupported resume_kind: {record.resume_kind}",
            "error_code": ErrorCode.APPROVAL_RESUME_INVALID.value,
            "type": "approval_resume",
            "approval_id": record.approval_id,
        },
        request_id=record.request_id,
        turn_id=record.turn_id,
    )
    return


def resume_tool_chain(orch, record: ApprovalRecord, *, timeout_s: float | None) -> None:
    raw_calls = record.resume_payload.get("tool_calls")
    if not isinstance(raw_calls, list) or not raw_calls:
        orch._emit(
            kind=EventKind.OPERATION_FAILED,
            payload={
                "error": "Missing tool_calls in approval resume payload.",
                "error_code": ErrorCode.APPROVAL_RESUME_INVALID.value,
                "type": "approval_resume",
                "approval_id": record.approval_id,
            },
            request_id=record.request_id,
            turn_id=record.turn_id,
        )
        return

    planned_calls = []
    for raw in raw_calls:
        if not isinstance(raw, dict):
            continue
        try:
            planned_calls.append(
                _planned_tool_call_from_descriptor(raw, read_artifact_text=orch._read_artifact_text)
            )
        except Exception as e:
            orch._emit(
                kind=EventKind.OPERATION_FAILED,
                payload={
                    "error": f"Invalid tool_call descriptor in approval resume payload: {e}",
                    "error_code": ErrorCode.APPROVAL_RESUME_INVALID.value,
                    "type": "approval_resume",
                    "approval_id": record.approval_id,
                },
                request_id=record.request_id,
                turn_id=record.turn_id,
            )
            return

    if not planned_calls:
        orch._emit(
            kind=EventKind.OPERATION_FAILED,
            payload={
                "error": "No valid tool calls to resume.",
                "error_code": ErrorCode.APPROVAL_RESUME_INVALID.value,
                "type": "approval_resume",
                "approval_id": record.approval_id,
            },
            request_id=record.request_id,
            turn_id=record.turn_id,
        )
        return

    handled = orch._handle_planned_tool_calls(
        planned_calls=planned_calls,
        request_id=record.request_id,
        turn_id=record.turn_id,
        timeout_s=timeout_s,
        skip_approval_tool_execution_id=planned_calls[0].tool_execution_id,
    )
    if not handled:
        return

    orch._continue_chat_operation(
        request_id=record.request_id,
        turn_id=record.turn_id,
        timeout_s=timeout_s,
        cancel=None,
    )

