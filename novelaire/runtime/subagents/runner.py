from __future__ import annotations

import fnmatch
import json
from dataclasses import dataclass
from typing import Any

from ..ids import new_id, now_ts_ms
from ..llm.client import LLMClient
from ..llm.errors import CancellationToken, LLMRequestError, ModelResolutionError
from ..llm.router import ModelRouter
from ..llm.trace import LLMTrace
from ..llm.types import (
    CanonicalMessage,
    CanonicalMessageRole,
    CanonicalRequest,
    ModelRequirements,
    ModelRole,
    ToolCall,
    ToolSpec,
)
from ..orchestrator_helpers import _canonical_request_to_redacted_dict, _summarize_text
from ..protocol import Event, EventKind
from ..stores import ArtifactStore
from ..subagents.presets import SubagentPreset
from ..tools.registry import ToolRegistry
from ..tools.runtime import InspectionDecision, ToolExecutionContext, ToolRuntime, ToolRuntimeError

def _tool_allowed(tool_name: str, patterns: list[str]) -> bool:
    for pat in patterns:
        pat = str(pat).strip()
        if not pat:
            continue
        if pat == tool_name or fnmatch.fnmatch(tool_name, pat):
            return True
    return False

def _json_or_text(text: str) -> dict[str, Any] | str:
    s = str(text or "").strip()
    if not s:
        return ""
    try:
        obj = json.loads(s)
    except Exception:
        return s
    if isinstance(obj, dict):
        return obj
    return s

def _emit_progress(ctx: ToolExecutionContext | None, *, message: str, subagent_run_id: str) -> None:
    if ctx is None or ctx.event_bus is None:
        return
    ctx.event_bus.publish(
        Event(
            kind=EventKind.TOOL_CALL_PROGRESS.value,
            payload={"message": message, "subagent_run_id": subagent_run_id},
            session_id=ctx.session_id,
            event_id=new_id("evt"),
            timestamp=now_ts_ms(),
            request_id=ctx.request_id,
            turn_id=ctx.turn_id,
            step_id=ctx.tool_execution_id,
        )
    )

def _emit_event(
    ctx: ToolExecutionContext | None,
    *,
    kind: EventKind,
    payload: dict[str, Any],
    subagent_run_id: str,
    step_id: str | None,
) -> None:
    if ctx is None or ctx.event_bus is None:
        return
    out = dict(payload)
    out["subagent_run_id"] = subagent_run_id
    ctx.event_bus.publish(
        Event(
            kind=kind.value,
            payload=out,
            session_id=ctx.session_id,
            event_id=new_id("evt"),
            timestamp=now_ts_ms(),
            request_id=ctx.request_id,
            turn_id=ctx.turn_id,
            step_id=step_id,
        )
    )

def _filter_tool_specs(registry: ToolRegistry, *, allowlist: list[str]) -> list[ToolSpec]:
    specs = registry.list_specs()
    out: list[ToolSpec] = []
    for s in specs:
        if s.name == "subagent__run":
            continue
        if _tool_allowed(s.name, allowlist):
            out.append(s)
    return out

def _context_to_text(context: Any) -> str | None:
    if context is None:
        return None
    if isinstance(context, str):
        return context.strip() or None
    if not isinstance(context, dict):
        return str(context).strip() or None

    parts: list[str] = []
    text = context.get("text")
    if isinstance(text, str) and text.strip():
        parts.append(text.strip())

    files = context.get("files")
    if isinstance(files, list) and files:
        file_lines: list[str] = []
        for item in files:
            if isinstance(item, str) and item.strip():
                file_lines.append(f"- {item.strip()}")
                continue
            if not isinstance(item, dict):
                continue
            path = item.get("path")
            if isinstance(path, str) and path.strip():
                max_chars = item.get("max_chars")
                if isinstance(max_chars, int) and max_chars > 0:
                    file_lines.append(f"- {path.strip()} (max_chars={max_chars})")
                else:
                    file_lines.append(f"- {path.strip()}")
        if file_lines:
            parts.append("Context files (read these with project tools if needed):\n" + "\n".join(file_lines))

    return "\n\n".join(parts).strip() or None

@dataclass(frozen=True, slots=True)
class SubagentReceipt:
    kind: str
    detail: dict[str, Any]

def run_subagent(
    *,
    preset: SubagentPreset,
    task: str,
    extra_context: Any,
    tool_allowlist: list[str],
    max_turns: int,
    max_tool_calls: int,
    llm_client: LLMClient,
    model_router: ModelRouter,
    tool_registry: ToolRegistry,
    tool_runtime: ToolRuntime,
    artifact_store: ArtifactStore,
    project_root,
    exec_context: ToolExecutionContext | None,
) -> dict[str, Any]:
    task = str(task or "").strip()
    if not task:
        raise ValueError("task must be non-empty.")

    subagent_run_id = new_id("subag")
    _emit_progress(exec_context, message=f"Subagent started: preset={preset.name}", subagent_run_id=subagent_run_id)

    system = preset.load_prompt().rstrip()
    allowed_tools_text = "\n".join(sorted(set(tool_allowlist)))
    system = (
        system
        + "\n\n"
        + "Allowed tools (enforced by the runner):\n"
        + allowed_tools_text
        + "\n\n"
        + "Hard constraints:\n"
        + "- Do NOT call subagent__run (recursion is forbidden).\n"
        + "- If a tool would require user approval, STOP and report that approval is required.\n"
    )

    user_parts = [f"Task:\n{task}"]
    ctx_text = _context_to_text(extra_context)
    if ctx_text:
        user_parts.append(f"Additional context:\n{ctx_text}")
    user_message = "\n\n".join(user_parts).strip()

    messages: list[CanonicalMessage] = [CanonicalMessage(role=CanonicalMessageRole.USER, content=user_message)]
    receipts: list[SubagentReceipt] = []
    executed_tool_calls = 0

    tool_specs = _filter_tool_specs(tool_registry, allowlist=tool_allowlist)
    cancel = CancellationToken()

    last_llm_response = None
    fallback_used = False
    selected_profile_id: str | None = None
    selected_role: ModelRole | None = None

    for turn_index in range(max_turns):
        _emit_progress(
            exec_context,
            message=f"Subagent turn {turn_index + 1}/{max_turns}: querying model",
            subagent_run_id=subagent_run_id,
        )

        request = CanonicalRequest(system=system, messages=list(messages), tools=tool_specs)
        context_ref = artifact_store.put(
            json.dumps(_canonical_request_to_redacted_dict(request), ensure_ascii=False),
            kind="llm_context",
            meta={"summary": f"Subagent request ({preset.name})"},
        )

        requirements = ModelRequirements(needs_streaming=False, needs_tools=bool(tool_specs))
        preferred_role = ModelRole.SUBAGENT if preset.name == "verifier" else ModelRole.TOOL_INTERPRETER
        try:
            resolved = model_router.resolve(role=preferred_role, requirements=requirements)
            selected_role = preferred_role
        except ModelResolutionError:
            resolved = model_router.resolve(role=ModelRole.MAIN, requirements=requirements)
            selected_role = ModelRole.MAIN
            fallback_used = True

        selected_profile_id = resolved.profile.profile_id
        _emit_event(
            exec_context,
            kind=EventKind.MODEL_SELECTED,
            payload={
                "role": selected_role.value,
                "profile_id": selected_profile_id,
                "provider_kind": resolved.profile.provider_kind.value,
                "model_name": resolved.profile.model_name,
                "requirements": {
                    "needs_streaming": resolved.requirements.needs_streaming,
                    "needs_tools": resolved.requirements.needs_tools,
                    "needs_structured_output": resolved.requirements.needs_structured_output,
                    "min_context_tokens": resolved.requirements.min_context_tokens,
                },
                "why": resolved.why,
                "preset": preset.name,
            },
            subagent_run_id=subagent_run_id,
            step_id=exec_context.tool_execution_id if exec_context is not None else None,
        )

        step_id = new_id("substep")
        _emit_event(
            exec_context,
            kind=EventKind.LLM_REQUEST_STARTED,
            payload={
                "role": selected_role.value,
                "context_ref": context_ref.to_dict(),
                "profile_id": selected_profile_id,
                "timeout_s": resolved.profile.timeout_s,
                "stream": False,
                "preset": preset.name,
                "turn_index": turn_index,
            },
            subagent_run_id=subagent_run_id,
            step_id=step_id,
        )

        trace = LLMTrace.maybe_create(
            project_root=project_root,
            session_id=exec_context.session_id if exec_context is not None else "unknown_session",
            request_id=exec_context.request_id if exec_context is not None else "unknown_request",
            turn_id=exec_context.turn_id if exec_context is not None else None,
            step_id=step_id,
        )
        if trace is not None:
            trace.record_meta(profile_id=selected_profile_id, context_ref=context_ref.to_dict(), operation="subagent_complete")
            trace.record_canonical_request(request)

        try:
            last_llm_response = llm_client.complete(
                role=selected_role,
                requirements=requirements,
                request=request,
                timeout_s=resolved.profile.timeout_s,
                cancel=cancel,
                trace=trace,
            )
        except LLMRequestError as e:
            receipts.append(SubagentReceipt(kind="llm_error", detail={"error": str(e), "error_code": e.code.value if e.code else None}))
            _emit_event(
                exec_context,
                kind=EventKind.LLM_REQUEST_FAILED,
                payload={
                    "error": str(e),
                    "error_code": e.code.value if e.code is not None else None,
                    "provider_kind": e.provider_kind.value if e.provider_kind is not None else None,
                    "profile_id": e.profile_id,
                    "model": e.model,
                    "retryable": e.retryable,
                    "details": e.details,
                    "preset": preset.name,
                },
                subagent_run_id=subagent_run_id,
                step_id=step_id,
            )
            break

        assistant_text = last_llm_response.text or ""
        messages.append(
            CanonicalMessage(
                role=CanonicalMessageRole.ASSISTANT,
                content=assistant_text,
                tool_calls=last_llm_response.tool_calls or None,
            )
        )
        receipts.append(SubagentReceipt(kind="assistant", detail={"text_summary": _summarize_text(assistant_text)}))

        out_ref = artifact_store.put(
            assistant_text,
            kind="chat_assistant",
            meta={"summary": _summarize_text(assistant_text)},
        )
        _emit_event(
            exec_context,
            kind=EventKind.LLM_RESPONSE_COMPLETED,
            payload={
                "profile_id": last_llm_response.profile_id,
                "provider_kind": last_llm_response.provider_kind.value,
                "model": last_llm_response.model,
                "output_ref": out_ref.to_dict(),
                "tool_calls": [
                    {"tool_execution_id": None, "tool_call_id": c.tool_call_id, "tool_name": c.name, "arguments_ref": None}
                    for c in (last_llm_response.tool_calls or [])
                ],
                "usage": (last_llm_response.usage.__dict__ if last_llm_response.usage is not None else None),
                "stop_reason": last_llm_response.stop_reason,
                "preset": preset.name,
                "turn_index": turn_index,
            },
            subagent_run_id=subagent_run_id,
            step_id=step_id,
        )

        tool_calls: list[ToolCall] = list(last_llm_response.tool_calls or [])
        if not tool_calls:
            break

        for call in tool_calls:
            if executed_tool_calls >= max_tool_calls:
                receipts.append(SubagentReceipt(kind="limit", detail={"reason": "max_tool_calls"}))
                break

            tool_name = call.name
            tool_call_id = call.tool_call_id or new_id("call")
            if tool_name == "subagent__run":
                receipts.append(SubagentReceipt(kind="recursion_blocked", detail={"tool_name": tool_name}))
                executed_tool_calls = max_tool_calls
                break

            if not _tool_allowed(tool_name, tool_allowlist):
                receipts.append(SubagentReceipt(kind="tool_denied", detail={"tool_name": tool_name, "reason": "not_allowlisted"}))
                executed_tool_calls = max_tool_calls
                break

            planned = tool_runtime.plan(
                tool_execution_id=new_id("tool"),
                tool_name=tool_name,
                tool_call_id=tool_call_id,
                arguments=call.arguments,
            )
            inspection = tool_runtime.inspect(planned)
            if inspection.decision is InspectionDecision.REQUIRE_APPROVAL:
                receipts.append(
                    SubagentReceipt(
                        kind="needs_approval",
                        detail={
                            "tool_name": tool_name,
                            "action_summary": inspection.action_summary,
                            "reason": inspection.reason,
                        },
                    )
                )
                executed_tool_calls = max_tool_calls
                break
            if inspection.decision is InspectionDecision.DENY:
                receipts.append(
                    SubagentReceipt(
                        kind="tool_denied",
                        detail={
                            "tool_name": tool_name,
                            "action_summary": inspection.action_summary,
                            "reason": inspection.reason,
                            "error_code": inspection.error_code.value if inspection.error_code is not None else None,
                        },
                    )
                )
                executed_tool_calls = max_tool_calls
                break

            _emit_event(
                exec_context,
                kind=EventKind.TOOL_CALL_START,
                payload={
                    "tool_execution_id": planned.tool_execution_id,
                    "tool_name": planned.tool_name,
                    "tool_call_id": planned.tool_call_id,
                    "summary": f"Subagent calls {planned.tool_name}",
                    "arguments_ref": planned.arguments_ref.to_dict(),
                    "preset": preset.name,
                },
                subagent_run_id=subagent_run_id,
                step_id=planned.tool_execution_id,
            )

            result = tool_runtime.execute(planned)
            executed_tool_calls += 1
            receipts.append(
                SubagentReceipt(
                    kind="tool_result",
                    detail={
                        "tool_name": result.tool_name,
                        "status": result.status,
                        "error_code": result.error_code.value if result.error_code is not None else None,
                        "error": result.error,
                        "duration_ms": result.duration_ms,
                        "tool_message_ref": result.tool_message_ref.to_dict() if result.tool_message_ref is not None else None,
                    },
                )
            )

            _emit_event(
                exec_context,
                kind=EventKind.TOOL_CALL_END,
                payload={
                    "tool_execution_id": result.tool_execution_id,
                    "tool_name": result.tool_name,
                    "tool_call_id": result.tool_call_id,
                    "summary": f"Subagent calls {result.tool_name}",
                    "status": result.status,
                    "duration_ms": result.duration_ms,
                    "output_ref": result.output_ref.to_dict() if result.output_ref is not None else None,
                    "tool_message_ref": result.tool_message_ref.to_dict() if result.tool_message_ref is not None else None,
                    "error_code": result.error_code.value if result.error_code is not None else None,
                    "error": result.error,
                    "preset": preset.name,
                },
                subagent_run_id=subagent_run_id,
                step_id=result.tool_execution_id,
            )

            if result.tool_message_content is None:
                raise ToolRuntimeError("Missing tool_message_content from tool execution.")

            messages.append(
                CanonicalMessage(
                    role=CanonicalMessageRole.TOOL,
                    content=result.tool_message_content,
                    tool_call_id=planned.tool_call_id,
                    tool_name=planned.tool_name,
                )
            )

        if executed_tool_calls >= max_tool_calls:
            break

    status = "completed"
    needs_approval = any(r.kind == "needs_approval" for r in receipts)
    denied = any(r.kind in {"tool_denied", "recursion_blocked"} for r in receipts)
    llm_error = any(r.kind == "llm_error" for r in receipts)
    if llm_error:
        status = "failed"
    elif needs_approval:
        status = "needs_approval"
    elif denied:
        status = "denied"
    elif last_llm_response is None:
        status = "failed"
    elif (last_llm_response.tool_calls or []) and executed_tool_calls >= max_tool_calls:
        status = "max_tool_calls_exceeded"
    elif turn_index + 1 >= max_turns and (last_llm_response.tool_calls or []):
        status = "max_turns_exceeded"

    transcript = {
        "preset": preset.name,
        "task": task,
        "turns": max_turns,
        "executed_tool_calls": executed_tool_calls,
        "status": status,
        "receipts": [{"kind": r.kind, "detail": r.detail} for r in receipts],
    }
    transcript_ref = artifact_store.put(
        json.dumps(transcript, ensure_ascii=False, sort_keys=True, indent=2),
        kind="subagent_transcript",
        meta={"summary": f"Subagent transcript ({preset.name})"},
    )

    report_text = last_llm_response.text if last_llm_response is not None else ""
    return {
        "subagent_run_id": subagent_run_id,
        "preset": preset.name,
        "status": status,
        "selected_role": selected_role.value if selected_role is not None else None,
        "selected_profile_id": selected_profile_id,
        "fallback_used": fallback_used,
        "tool_allowlist": tool_allowlist,
        "limits": {"max_turns": max_turns, "max_tool_calls": max_tool_calls},
        "executed_tool_calls": executed_tool_calls,
        "report": _json_or_text(report_text),
        "transcript_ref": transcript_ref.to_dict(),
    }
