from __future__ import annotations

import json

from .approval import ApprovalRecord, ApprovalStatus
from .error_codes import ErrorCode
from .ids import new_id, now_ts_ms
from .llm.types import CanonicalMessage, CanonicalMessageRole
from .protocol import EventKind, OpKind
from .tools import InspectionDecision, PlannedToolCall, ToolExecutionContext, ToolRuntimeError
from .orchestrator_helpers import _planned_tool_call_descriptor, _summarize_tool_for_ui


def _diff_add_del_counts(unified_diff_text: str) -> tuple[int, int]:
    adds = 0
    dels = 0
    for line in str(unified_diff_text).splitlines():
        if line.startswith("+++ ") or line.startswith("--- "):
            continue
        if line.startswith("+"):
            adds += 1
            continue
        if line.startswith("-"):
            dels += 1
            continue
    return adds, dels


def _elide_tail(s: str, max_chars: int) -> str:
    s = str(s)
    if max_chars <= 0 or len(s) <= max_chars:
        return s
    return s[: max(0, max_chars - 1)].rstrip() + "…"


def _unified_diff_changed_lines(unified_diff_text: str, *, max_lines: int = 12, max_line_chars: int = 180) -> list[str]:
    """
    Return a compact, Codex-style preview of changed lines with line numbers.

    We intentionally only show +/- lines (not context), and use the line numbers
    implied by unified diff hunk headers:
      @@ -old_start,old_len +new_start,new_len @@
    """

    lines = str(unified_diff_text).splitlines()
    out: list[str] = []

    old_line_no: int | None = None
    new_line_no: int | None = None

    def _parse_hunk_header(h: str) -> tuple[int, int] | None:
        # Example: "@@ -32,7 +32,7 @@"
        if not h.startswith("@@"):
            return None
        try:
            parts = h.split()
            old_part = next(p for p in parts if p.startswith("-"))
            new_part = next(p for p in parts if p.startswith("+"))
            old_start = int(old_part[1:].split(",")[0])
            new_start = int(new_part[1:].split(",")[0])
            return old_start, new_start
        except Exception:
            return None

    for line in lines:
        if line.startswith("--- ") or line.startswith("+++ "):
            continue
        if line.startswith("@@"):
            parsed = _parse_hunk_header(line)
            if parsed is not None:
                old_line_no, new_line_no = parsed
            else:
                old_line_no, new_line_no = None, None
            continue

        if old_line_no is None or new_line_no is None:
            continue

        if line.startswith(" "):
            old_line_no += 1
            new_line_no += 1
            continue
        if line.startswith("-"):
            out.append(f"{old_line_no:>5} {_elide_tail(line, max_line_chars)}")
            old_line_no += 1
        elif line.startswith("+"):
            out.append(f"{new_line_no:>5} {_elide_tail(line, max_line_chars)}")
            new_line_no += 1
        else:
            continue

        if len(out) >= max_lines:
            break

    return out


def _tool_ui_details(tool_name: str, tool_message_content: str | None) -> list[str] | None:
    if tool_name not in {"project__apply_patch", "project__apply_edits"}:
        return None
    if not isinstance(tool_message_content, str) or not tool_message_content.strip():
        return None
    try:
        msg = json.loads(tool_message_content)
    except Exception:
        return None
    if not isinstance(msg, dict) or msg.get("ok") is not True:
        return None
    result = msg.get("result")
    if not isinstance(result, dict):
        return None

    diffs = result.get("diffs")
    if not isinstance(diffs, list) or not diffs:
        return None

    changed_files = result.get("changed_files")
    total_changed = len(changed_files) if isinstance(changed_files, list) else None

    out: list[str] = []
    file_headers = 0
    for item in diffs:
        if not isinstance(item, dict):
            continue
        path = item.get("path")
        if not isinstance(path, str) or not path.strip():
            continue
        diff_text = item.get("diff") or ""
        adds, dels = _diff_add_del_counts(str(diff_text))
        suffix = f"(+{adds} -{dels})"
        if item.get("truncated") is True:
            suffix += " (diff truncated)"
        moved_from = item.get("moved_from")
        if isinstance(moved_from, str) and moved_from.strip():
            out.append(f"{path} {suffix} (moved from {moved_from})")
        else:
            out.append(f"{path} {suffix}")
        file_headers += 1

        # Show a small preview of changed lines (Codex-style).
        preview = _unified_diff_changed_lines(str(diff_text))
        out.extend(preview)

    if total_changed is not None and total_changed > file_headers:
        out.append(f"... ({total_changed - file_headers} more file(s))")

    return out or None


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
            ctx = ToolExecutionContext(
                session_id=orch.session_id,
                request_id=request_id,
                turn_id=turn_id,
                tool_execution_id=planned.tool_execution_id,
                event_bus=orch.event_bus,
            )
            result = orch.tool_runtime.execute(planned, context=ctx)
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
                "details": _tool_ui_details(result.tool_name, result.tool_message_content),
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

        # Always record tool results (including failures) into the conversation history
        # so the model can self-correct on subsequent turns.
        if result.tool_message_content is not None:
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

    return True
