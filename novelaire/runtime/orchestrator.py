from __future__ import annotations

import json
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Iterable, Iterator

from .approval import ApprovalDecision, ApprovalRecord, ApprovalStatus
from .error_codes import ErrorCode
from .event_bus import EventBus
from .ids import new_id, now_ts_ms
from .protocol import Event, EventKind, Op, OpKind
from .stores import ApprovalStore, ArtifactStore, EventLogStore, SessionStore

from .llm.client import LLMClient
from .llm.config import ModelConfig
from .llm.errors import CancellationToken, LLMRequestError, ModelResolutionError
from .llm.router import ModelRouter
from .llm.types import (
    CanonicalMessage,
    CanonicalMessageRole,
    CanonicalRequest,
    ModelRequirements,
    ModelRole,
    ProviderKind,
    ToolCall,
)
from .tools import (
    InspectionDecision,
    ProjectReadTextTool,
    ProjectSearchTextTool,
    ProjectTextEditorTool,
    ProjectWriteTextTool,
    PlannedToolCall,
    ShellRunTool,
    ToolExecutionResult,
    ToolRegistry,
    ToolRuntime,
    ToolRuntimeError,
)

DEFAULT_SYSTEM_PROMPT = """You are Novelaire, a local CLI assistant for a writing project.

You may be provided with a set of tools. Use tools when you need to inspect or change project files.
Never claim you can browse the internet or accept file uploads. You can only access files via the provided tools.

When asked what tools you can use, list the available tool names and briefly explain what each does.
Do not invent tools. If tools are not provided, say tool calling is disabled and ask the user to paste content instead.
"""


@dataclass(slots=True)
class Orchestrator:
    project_root: Path
    session_id: str
    event_bus: EventBus
    session_store: SessionStore
    event_log_store: EventLogStore
    artifact_store: ArtifactStore
    approval_store: ApprovalStore
    llm_client: LLMClient
    model_router: ModelRouter
    tools_enabled: bool = False
    tool_registry: ToolRegistry | None = None
    tool_runtime: ToolRuntime | None = None
    system_prompt: str | None = None
    _history: list[CanonicalMessage] | None = None
    schema_version: str = "0.1"

    @staticmethod
    def for_session(
        *,
        project_root: Path,
        session_id: str,
        event_bus: EventBus,
        session_store: SessionStore,
        event_log_store: EventLogStore,
        artifact_store: ArtifactStore,
        approval_store: ApprovalStore,
        model_config: ModelConfig,
        system_prompt: str | None = None,
        tools_enabled: bool = False,
    ) -> "Orchestrator":
        effective_system_prompt = DEFAULT_SYSTEM_PROMPT if system_prompt is None else system_prompt
        router = ModelRouter(model_config)
        registry = ToolRegistry()
        registry.register(ProjectReadTextTool())
        registry.register(ProjectWriteTextTool())
        registry.register(ProjectTextEditorTool())
        registry.register(ProjectSearchTextTool())
        registry.register(ShellRunTool())
        tool_runtime = ToolRuntime(project_root=project_root, registry=registry, artifact_store=artifact_store)
        return Orchestrator(
            project_root=project_root,
            session_id=session_id,
            event_bus=event_bus,
            session_store=session_store,
            event_log_store=event_log_store,
            artifact_store=artifact_store,
            approval_store=approval_store,
            llm_client=LLMClient(model_config),
            model_router=router,
            tools_enabled=tools_enabled,
            tool_registry=registry,
            tool_runtime=tool_runtime,
            system_prompt=effective_system_prompt,
            _history=[],
        )

    def load_history_from_events(self) -> None:
        history: list[CanonicalMessage] = []
        for event in self.event_log_store.read(self.session_id):
            if event.kind == EventKind.OPERATION_STARTED.value:
                ref_raw = event.payload.get("input_ref")
                if isinstance(ref_raw, dict):
                    text = self._read_artifact_text(ref_raw)
                    history.append(CanonicalMessage(role=CanonicalMessageRole.USER, content=text))
            elif event.kind == EventKind.LLM_RESPONSE_COMPLETED.value:
                ref_raw = event.payload.get("output_ref")
                if isinstance(ref_raw, dict):
                    text = self._read_artifact_text(ref_raw)
                    tool_calls = _tool_calls_from_payload(
                        event.payload.get("tool_calls"), read_artifact_text=self._read_artifact_text
                    )
                    history.append(
                        CanonicalMessage(
                            role=CanonicalMessageRole.ASSISTANT,
                            content=text,
                            tool_calls=tool_calls or None,
                        )
                    )
            elif event.kind == EventKind.TOOL_CALL_END.value:
                payload = event.payload
                tool_call_id = payload.get("tool_call_id")
                tool_name = payload.get("tool_name")
                ref_raw = payload.get("tool_message_ref")
                if (
                    isinstance(tool_call_id, str)
                    and tool_call_id
                    and isinstance(tool_name, str)
                    and tool_name
                    and isinstance(ref_raw, dict)
                ):
                    content = self._read_artifact_text(ref_raw)
                    history.append(
                        CanonicalMessage(
                            role=CanonicalMessageRole.TOOL,
                            content=content,
                            tool_call_id=tool_call_id,
                            tool_name=tool_name,
                        )
                    )
        self._history = history

    def handle(
        self,
        op: Op,
        *,
        timeout_s: float | None = None,
        cancel: CancellationToken | None = None,
    ) -> None:
        if op.session_id != self.session_id:
            raise ValueError("Op session_id does not match orchestrator session.")

        if op.kind == OpKind.APPROVAL_DECISION.value:
            self._handle_approval_decision(op, timeout_s=timeout_s)
            return

        pending = self.approval_store.list(session_id=self.session_id, status=ApprovalStatus.PENDING)
        if pending:
            self._emit(
                kind=EventKind.OPERATION_FAILED,
                payload={
                    "error": "Session has pending approvals.",
                    "error_code": ErrorCode.APPROVAL_PENDING.value,
                    "approval_ids": [p.approval_id for p in pending],
                },
                request_id=op.request_id,
                turn_id=op.turn_id,
            )
            return

        if op.kind == OpKind.CHAT.value:
            self._handle_chat(op, timeout_s=timeout_s, cancel=cancel)
            return

        raise NotImplementedError(f"Unsupported op kind: {op.kind}")

    def _emit(
        self,
        *,
        kind: EventKind,
        payload: dict[str, Any],
        request_id: str | None,
        turn_id: str | None,
        step_id: str | None = None,
    ) -> Event:
        event = Event(
            kind=kind.value,
            payload=payload,
            session_id=self.session_id,
            event_id=new_id("evt"),
            timestamp=now_ts_ms(),
            request_id=request_id,
            turn_id=turn_id,
            step_id=step_id,
            schema_version=self.schema_version,
        )
        self.event_bus.publish(event)
        self.session_store.update_session(
            self.session_id,
            {
                "last_request_id": request_id,
                "last_event_id": event.event_id,
            },
        )
        return event

    def _handle_chat(
        self,
        op: Op,
        *,
        timeout_s: float | None,
        skip_approval: bool = False,
        cancel: CancellationToken | None = None,
    ) -> None:
        user_text = str(op.payload.get("text") or "")
        if not user_text.strip():
            self._emit(
                kind=EventKind.OPERATION_FAILED,
                payload={"error": "Empty input.", "error_code": ErrorCode.BAD_REQUEST.value},
                request_id=op.request_id,
                turn_id=op.turn_id,
            )
            return

        if self._history is None:
            self._history = []

        input_ref = self.artifact_store.put(
            user_text,
            kind="chat_user",
            meta={"summary": _summarize_text(user_text)},
        )
        self._emit(
            kind=EventKind.OPERATION_STARTED,
            payload={"op_kind": OpKind.CHAT.value, "input_ref": input_ref.to_dict()},
            request_id=op.request_id,
            turn_id=op.turn_id,
        )

        self._history.append(CanonicalMessage(role=CanonicalMessageRole.USER, content=user_text))

        require_approval = (not skip_approval) and bool(op.payload.get("require_approval"))
        if require_approval:
            approval_id = new_id("appr")
            record = ApprovalRecord(
                approval_id=approval_id,
                session_id=self.session_id,
                request_id=op.request_id,
                created_at=now_ts_ms(),
                status=ApprovalStatus.PENDING,
                turn_id=op.turn_id,
                action_summary="Approve to continue: execute this chat operation.",
                risk_level=str(op.payload.get("risk_level") or "low"),
                options=["approve", "deny"],
                reason=str(op.payload.get("reason")) if op.payload.get("reason") is not None else None,
                diff_ref=dict(op.payload.get("diff_ref")) if op.payload.get("diff_ref") is not None else None,
                resume_kind="chat_continue",
                resume_payload={"tools_enabled": self.tools_enabled},
            )
            self.approval_store.create(record)
            self._emit(
                kind=EventKind.APPROVAL_REQUIRED,
                payload={
                    "approval_id": approval_id,
                    "action_summary": record.action_summary,
                    "risk_level": record.risk_level,
                    "options": record.options,
                    "reason": record.reason,
                    "diff_ref": record.diff_ref,
                },
                request_id=op.request_id,
                turn_id=op.turn_id,
            )
            return

        self._continue_chat_operation(
            request_id=op.request_id,
            turn_id=op.turn_id,
            timeout_s=timeout_s,
            cancel=cancel,
        )

    def _continue_chat_operation(
        self,
        *,
        request_id: str,
        turn_id: str | None,
        timeout_s: float | None,
        cancel: CancellationToken | None,
    ) -> None:
        if self._history is None:
            self._history = []
        if self.tool_registry is None or self.tool_runtime is None:
            raise RuntimeError("Tool runtime not initialized.")

        max_turns = 8
        for turn_index in range(max_turns):
            step_id = new_id("step")
            request = self._build_request()
            requirements = ModelRequirements(
                needs_streaming=True,
                needs_tools=bool(request.tools),
            )
            try:
                resolved = self.model_router.resolve(role=ModelRole.MAIN, requirements=requirements)
            except ModelResolutionError as e:
                self._emit(
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
                self._emit(
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
                return

            self._emit(
                kind=EventKind.MODEL_SELECTED,
                payload={
                    "role": resolved.role.value,
                    "profile_id": resolved.profile.profile_id,
                    "provider_kind": resolved.profile.provider_kind.value,
                    "model_name": resolved.profile.model_name,
                    "requirements": {
                        "needs_streaming": resolved.requirements.needs_streaming,
                        "needs_tools": resolved.requirements.needs_tools,
                        "needs_structured_output": resolved.requirements.needs_structured_output,
                        "min_context_tokens": resolved.requirements.min_context_tokens,
                    },
                    "why": resolved.why,
                },
                request_id=request_id,
                turn_id=turn_id,
                step_id=step_id,
            )

            context_ref = self._write_context_ref(request)
            effective_timeout_s = timeout_s if timeout_s is not None else resolved.profile.timeout_s
            caps = resolved.profile.capabilities.with_provider_defaults(resolved.profile.provider_kind)
            use_streaming = caps.supports_streaming is True
            if use_streaming:
                response, planned_calls = self._run_llm_stream(
                    request=request,
                    context_ref=context_ref.to_dict(),
                    profile_id=resolved.profile.profile_id,
                    request_id=request_id,
                    turn_id=turn_id,
                    step_id=step_id,
                    timeout_s=effective_timeout_s,
                    cancel=cancel,
                )
            else:
                response, planned_calls = self._run_llm_complete(
                    request=request,
                    context_ref=context_ref.to_dict(),
                    profile_id=resolved.profile.profile_id,
                    request_id=request_id,
                    turn_id=turn_id,
                    step_id=step_id,
                    timeout_s=effective_timeout_s,
                    cancel=cancel,
                )
            if response is None:
                return

            self._history.append(
                CanonicalMessage(
                    role=CanonicalMessageRole.ASSISTANT,
                    content=response.text,
                    tool_calls=response.tool_calls or None,
                )
            )

            if not response.tool_calls:
                self._emit(
                    kind=EventKind.OPERATION_COMPLETED,
                    payload={"op_kind": OpKind.CHAT.value},
                    request_id=request_id,
                    turn_id=turn_id,
                )
                return

            if not self.tools_enabled:
                self._emit(
                    kind=EventKind.OPERATION_FAILED,
                    payload={
                        "error": "Model returned tool calls but tools are disabled for this session.",
                        "error_code": ErrorCode.TOOL_CALLS_DISABLED.value,
                        "type": "tool_calls_disabled",
                    },
                    request_id=request_id,
                    turn_id=turn_id,
                )
                return

            handled = self._handle_planned_tool_calls(
                planned_calls=planned_calls,
                request_id=request_id,
                turn_id=turn_id,
                timeout_s=timeout_s,
                skip_approval_tool_execution_id=None,
            )
            if not handled:
                return

        self._emit(
            kind=EventKind.OPERATION_FAILED,
            payload={
                "error": "Exceeded max tool turns for this operation.",
                "error_code": ErrorCode.TOOL_LOOP_LIMIT.value,
                "type": "tool_loop_limit",
            },
            request_id=request_id,
            turn_id=turn_id,
        )

    def _build_request(self) -> CanonicalRequest:
        tools = []
        if self.tools_enabled and self.tool_registry is not None:
            tools = self.tool_registry.list_specs()
        return CanonicalRequest(system=self.system_prompt, messages=list(self._history or []), tools=tools)

    def _write_context_ref(self, request: CanonicalRequest) -> "ArtifactRef":
        payload = _canonical_request_to_redacted_dict(request)
        return self.artifact_store.put(
            json.dumps(payload, ensure_ascii=False),
            kind="llm_context",
            meta={"summary": "CanonicalRequest (redacted)"},
        )

    def _run_llm_stream(
        self,
        *,
        request: CanonicalRequest,
        context_ref: dict[str, Any],
        profile_id: str,
        request_id: str,
        turn_id: str | None,
        step_id: str,
        timeout_s: float | None,
        cancel: CancellationToken | None,
    ) -> tuple[Any | None, list[PlannedToolCall]]:
        cancel = cancel or CancellationToken()
        stream_iter = None
        self._emit(
            kind=EventKind.LLM_REQUEST_STARTED,
            payload={
                "role": ModelRole.MAIN.value,
                "context_ref": context_ref,
                "profile_id": profile_id,
                "timeout_s": timeout_s,
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
            stream_iter = self.llm_client.stream(
                role=ModelRole.MAIN,
                requirements=ModelRequirements(needs_streaming=True),
                request=request,
                timeout_s=timeout_s,
                cancel=cancel,
            )
            for ev in stream_iter:
                if ev.kind.value == "text_delta" and ev.text_delta is not None:
                    delta_buf.append(ev.text_delta)
                    now = time.monotonic()
                    # Keep the UI responsive: flush frequently by time or size, not only on large chunks.
                    if (
                        sum(len(p) for p in delta_buf) >= 32
                        or "\n" in ev.text_delta
                        or (now - last_emit) >= 0.08
                    ):
                        emitted = "".join(delta_buf)
                        self._emit(
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
                    self._emit(
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
            if stream_iter is not None:
                try:
                    close = getattr(stream_iter, "close", None)
                    if callable(close):
                        close()
                except Exception:
                    pass
            if delta_buf:
                self._emit(
                    kind=EventKind.LLM_RESPONSE_DELTA,
                    payload={"text_delta": "".join(delta_buf)},
                    request_id=request_id,
                    turn_id=turn_id,
                    step_id=step_id,
                )
            self._emit(
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
                self._emit(
                    kind=EventKind.LLM_REQUEST_FAILED,
                    payload={
                        "error": str(e),
                        "error_code": e.code.value,
                        "code": e.code.value if e.code is not None else None,
                        "provider_kind": e.provider_kind.value if e.provider_kind is not None else None,
                        "profile_id": e.profile_id,
                        "model": e.model,
                        "retryable": e.retryable,
                    },
                    request_id=request_id,
                    turn_id=turn_id,
                    step_id=step_id,
                )
                self._emit(
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
            self._emit(
                kind=EventKind.LLM_REQUEST_FAILED,
                payload={
                    "error": str(e),
                    "error_code": e.code.value,
                    "code": e.code.value if e.code is not None else None,
                    "provider_kind": e.provider_kind.value if e.provider_kind is not None else None,
                    "profile_id": e.profile_id,
                    "model": e.model,
                    "retryable": e.retryable,
                },
                request_id=request_id,
                turn_id=turn_id,
                step_id=step_id,
            )
            self._emit(
                kind=EventKind.OPERATION_FAILED,
                payload={"error": str(e), "error_code": e.code.value, "type": "llm_request"},
                request_id=request_id,
                turn_id=turn_id,
                step_id=step_id,
            )
            return None, []
        except ModelResolutionError as e:
            self._emit(
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
            self._emit(
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
            self._emit(
                kind=EventKind.LLM_RESPONSE_DELTA,
                payload={"text_delta": emitted},
                request_id=request_id,
                turn_id=turn_id,
                step_id=step_id,
            )
            streamed_parts.append(emitted)

        if final_response is None:
            self._emit(
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

        planned_calls: list[PlannedToolCall] = []
        if final_response.tool_calls:
            if self.tool_runtime is None:
                raise RuntimeError("Tool runtime not initialized.")
            try:
                for call in final_response.tool_calls:
                    planned_calls.append(
                        self.tool_runtime.plan(
                            tool_execution_id=new_id("tool"),
                            tool_name=call.name,
                            tool_call_id=call.tool_call_id or "",
                            arguments=call.arguments,
                        )
                    )
            except ToolRuntimeError as e:
                self._emit(
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
                return None, []

        usage = final_response.usage.__dict__ if final_response.usage is not None else None
        assistant_text = final_response.text
        output_ref = self.artifact_store.put(
            assistant_text,
            kind="chat_assistant",
            meta={"summary": _summarize_text(assistant_text)},
        )

        self._emit(
            kind=EventKind.LLM_RESPONSE_COMPLETED,
            payload={
                "profile_id": final_response.profile_id,
                "provider_kind": final_response.provider_kind.value,
                "model": final_response.model,
                "output_ref": output_ref.to_dict(),
                "tool_calls": [_planned_tool_call_descriptor(p) for p in planned_calls],
                "usage": usage,
                "stop_reason": final_response.stop_reason,
            },
            request_id=request_id,
            turn_id=turn_id,
            step_id=step_id,
        )

        return final_response, planned_calls

    def _run_llm_complete(
        self,
        *,
        request: CanonicalRequest,
        context_ref: dict[str, Any],
        profile_id: str,
        request_id: str,
        turn_id: str | None,
        step_id: str,
        timeout_s: float | None,
        cancel: CancellationToken | None,
    ) -> tuple[Any | None, list[PlannedToolCall]]:
        cancel = cancel or CancellationToken()
        self._emit(
            kind=EventKind.LLM_REQUEST_STARTED,
            payload={
                "role": ModelRole.MAIN.value,
                "context_ref": context_ref,
                "profile_id": profile_id,
                "timeout_s": timeout_s,
                "stream": False,
            },
            request_id=request_id,
            turn_id=turn_id,
            step_id=step_id,
        )

        try:
            final_response = self.llm_client.complete(
                role=ModelRole.MAIN,
                requirements=ModelRequirements(needs_streaming=False, needs_tools=bool(request.tools)),
                request=request,
                timeout_s=timeout_s,
                cancel=cancel,
            )
        except LLMRequestError as e:
            self._emit(
                kind=EventKind.LLM_REQUEST_FAILED,
                payload={
                    "error": str(e),
                    "error_code": e.code.value,
                    "code": e.code.value if e.code is not None else None,
                    "provider_kind": e.provider_kind.value if e.provider_kind is not None else None,
                    "profile_id": e.profile_id,
                    "model": e.model,
                    "retryable": e.retryable,
                },
                request_id=request_id,
                turn_id=turn_id,
                step_id=step_id,
            )
            if e.code is ErrorCode.CANCELLED:
                self._emit(
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
            self._emit(
                kind=EventKind.OPERATION_FAILED,
                payload={"error": str(e), "error_code": e.code.value, "type": "llm_request"},
                request_id=request_id,
                turn_id=turn_id,
                step_id=step_id,
            )
            return None, []

        assistant_text = final_response.text
        if assistant_text:
            self._emit(
                kind=EventKind.LLM_RESPONSE_DELTA,
                payload={"text_delta": assistant_text},
                request_id=request_id,
                turn_id=turn_id,
                step_id=step_id,
            )

        planned_calls: list[PlannedToolCall] = []
        if final_response.tool_calls:
            if self.tool_runtime is None:
                raise RuntimeError("Tool runtime not initialized.")
            try:
                for call in final_response.tool_calls:
                    planned_calls.append(
                        self.tool_runtime.plan(
                            tool_execution_id=new_id("tool"),
                            tool_name=call.name,
                            tool_call_id=call.tool_call_id or "",
                            arguments=call.arguments,
                        )
                    )
            except ToolRuntimeError as e:
                self._emit(
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
                return None, []

        usage = final_response.usage.__dict__ if final_response.usage is not None else None
        output_ref = self.artifact_store.put(
            assistant_text,
            kind="chat_assistant",
            meta={"summary": _summarize_text(assistant_text)},
        )
        self._emit(
            kind=EventKind.LLM_RESPONSE_COMPLETED,
            payload={
                "profile_id": final_response.profile_id,
                "provider_kind": final_response.provider_kind.value,
                "model": final_response.model,
                "output_ref": output_ref.to_dict(),
                "tool_calls": [_planned_tool_call_descriptor(p) for p in planned_calls],
                "usage": usage,
                "stop_reason": final_response.stop_reason,
                "stream": False,
            },
            request_id=request_id,
            turn_id=turn_id,
            step_id=step_id,
        )

        return final_response, planned_calls

    def _handle_planned_tool_calls(
        self,
        *,
        planned_calls: list[PlannedToolCall],
        request_id: str,
        turn_id: str | None,
        timeout_s: float | None,
        skip_approval_tool_execution_id: str | None,
    ) -> bool:
        if self.tool_runtime is None:
            raise RuntimeError("Tool runtime not initialized.")

        for idx, planned in enumerate(planned_calls):
            inspection = self.tool_runtime.inspect(planned)
            if inspection.decision is InspectionDecision.DENY:
                code = inspection.error_code or ErrorCode.TOOL_DENIED
                self._emit(
                    kind=EventKind.TOOL_CALL_END,
                    payload={
                        "tool_execution_id": planned.tool_execution_id,
                        "tool_name": planned.tool_name,
                        "tool_call_id": planned.tool_call_id,
                        "status": "denied",
                        "error_code": code.value,
                        "error": inspection.reason or inspection.action_summary,
                    },
                    request_id=request_id,
                    turn_id=turn_id,
                    step_id=planned.tool_execution_id,
                )
                self._emit(
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

            if inspection.decision is InspectionDecision.REQUIRE_APPROVAL and planned.tool_execution_id != skip_approval_tool_execution_id:
                approval_id = new_id("appr")
                remaining = planned_calls[idx:]
                record = ApprovalRecord(
                    approval_id=approval_id,
                    session_id=self.session_id,
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
                self.approval_store.create(record)
                self._emit(
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
                        "arguments_ref": planned.arguments_ref.to_dict(),
                    },
                    request_id=request_id,
                    turn_id=turn_id,
                    step_id=planned.tool_execution_id,
                )
                return False

            self._emit(
                kind=EventKind.TOOL_CALL_START,
                payload={
                    "tool_execution_id": planned.tool_execution_id,
                    "tool_name": planned.tool_name,
                    "tool_call_id": planned.tool_call_id,
                    "arguments_ref": planned.arguments_ref.to_dict(),
                },
                request_id=request_id,
                turn_id=turn_id,
                step_id=planned.tool_execution_id,
            )
            try:
                result = self.tool_runtime.execute(planned)
            except KeyboardInterrupt:
                self._emit(
                    kind=EventKind.TOOL_CALL_END,
                    payload={
                        "tool_execution_id": planned.tool_execution_id,
                        "tool_name": planned.tool_name,
                        "tool_call_id": planned.tool_call_id,
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
                self._emit(
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
            self._emit(
                kind=EventKind.TOOL_CALL_END,
                payload={
                    "tool_execution_id": result.tool_execution_id,
                    "tool_name": result.tool_name,
                    "tool_call_id": result.tool_call_id,
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

            if result.status != "succeeded" or result.tool_message_content is None:
                op_code = result.error_code or ErrorCode.TOOL_FAILED
                self._emit(
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

            if self._history is None:
                self._history = []
            self._history.append(
                CanonicalMessage(
                    role=CanonicalMessageRole.TOOL,
                    content=result.tool_message_content,
                    tool_call_id=planned.tool_call_id,
                    tool_name=planned.tool_name,
                )
            )

        return True

    def _handle_approval_decision(self, op: Op, *, timeout_s: float | None) -> None:
        self._emit(
            kind=EventKind.OPERATION_STARTED,
            payload={"op_kind": OpKind.APPROVAL_DECISION.value},
            request_id=op.request_id,
            turn_id=op.turn_id,
        )

        approval_id = str(op.payload.get("approval_id") or "")
        decision_raw = str(op.payload.get("decision") or "")
        note = op.payload.get("note")

        if not approval_id:
            self._emit(
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
            record = self.approval_store.get(approval_id)
        except FileNotFoundError:
            self._emit(
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

        if record.session_id != self.session_id:
            self._emit(
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
            self._emit(
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
            self._emit(
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
            self.approval_store.update(updated)
            self._emit(
                kind=EventKind.APPROVAL_GRANTED,
                payload={"approval_id": approval_id, "decision": decision_obj},
                request_id=record.request_id,
                turn_id=record.turn_id,
            )
            self._emit(
                kind=EventKind.OPERATION_COMPLETED,
                payload={"op_kind": OpKind.APPROVAL_DECISION.value, "approval_id": approval_id},
                request_id=op.request_id,
                turn_id=op.turn_id,
            )
            self._resume_from_approval(updated, timeout_s=timeout_s)
            return

        if decision is ApprovalDecision.DENY:
            updated = replace(
                record,
                status=ApprovalStatus.DENIED,
                decision=decision_obj,
            )
            self.approval_store.update(updated)
            self._emit(
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
                    if (
                        isinstance(tool_execution_id, str)
                        and tool_execution_id
                        and isinstance(tool_name, str)
                        and tool_name
                        and isinstance(tool_call_id, str)
                        and tool_call_id
                    ):
                        self._emit(
                            kind=EventKind.TOOL_CALL_END,
                            payload={
                                "tool_execution_id": tool_execution_id,
                                "tool_name": tool_name,
                                "tool_call_id": tool_call_id,
                                "status": "cancelled",
                                "error_code": ErrorCode.CANCELLED.value,
                                "error": "Approval denied.",
                            },
                            request_id=record.request_id,
                            turn_id=record.turn_id,
                        )
            self._emit(
                kind=EventKind.OPERATION_CANCELLED,
                payload={
                    "op_kind": OpKind.CHAT.value,
                    "approval_id": approval_id,
                    "error_code": ErrorCode.CANCELLED.value,
                },
                request_id=record.request_id,
                turn_id=record.turn_id,
            )
            self._emit(
                kind=EventKind.OPERATION_COMPLETED,
                payload={"op_kind": OpKind.APPROVAL_DECISION.value, "approval_id": approval_id},
                request_id=op.request_id,
                turn_id=op.turn_id,
            )
            return

        self._emit(
            kind=EventKind.OPERATION_FAILED,
            payload={
                "error": f"Decision not supported yet: {decision.value}",
                "error_code": ErrorCode.APPROVAL_DECISION_INVALID.value,
                "type": "approval_decision",
            },
            request_id=op.request_id,
            turn_id=op.turn_id,
        )

    def _resume_from_approval(self, record: ApprovalRecord, *, timeout_s: float | None) -> None:
        if record.resume_kind in ("chat_continue", "chat_llm"):
            self._continue_chat_operation(
                request_id=record.request_id,
                turn_id=record.turn_id,
                timeout_s=timeout_s,
                cancel=None,
            )
            return

        if record.resume_kind == "tool_chain":
            self._resume_tool_chain(record, timeout_s=timeout_s)
            return

        self._emit(
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

    def _resume_tool_chain(self, record: ApprovalRecord, *, timeout_s: float | None) -> None:
        raw_calls = record.resume_payload.get("tool_calls")
        if not isinstance(raw_calls, list) or not raw_calls:
            self._emit(
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

        planned_calls: list[PlannedToolCall] = []
        for raw in raw_calls:
            if not isinstance(raw, dict):
                continue
            try:
                planned_calls.append(
                    _planned_tool_call_from_descriptor(raw, read_artifact_text=self._read_artifact_text)
                )
            except Exception as e:
                self._emit(
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
            self._emit(
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

        handled = self._handle_planned_tool_calls(
            planned_calls=planned_calls,
            request_id=record.request_id,
            turn_id=record.turn_id,
            timeout_s=timeout_s,
            skip_approval_tool_execution_id=planned_calls[0].tool_execution_id,
        )
        if not handled:
            return

        self._continue_chat_operation(
            request_id=record.request_id,
            turn_id=record.turn_id,
            timeout_s=timeout_s,
            cancel=None,
        )

    def _read_artifact_text(self, ref_dict: dict[str, Any]) -> str:
        from .protocol import ArtifactRef

        ref = ArtifactRef.from_dict(ref_dict)
        data = self.artifact_store.get(ref)
        return data.decode("utf-8", errors="replace")


def _summarize_text(text: str, *, max_len: int = 160) -> str:
    s = " ".join(text.strip().split())
    if len(s) <= max_len:
        return s
    return s[: max_len - 1] + "…"


def _canonical_request_to_redacted_dict(request: CanonicalRequest) -> dict[str, Any]:
    return {
        "system": request.system,
        "messages": [_canonical_message_to_redacted_dict(m) for m in request.messages],
        "params": dict(request.params),
        "tools": [t.__dict__ for t in request.tools],
    }


def _canonical_message_to_redacted_dict(msg: CanonicalMessage) -> dict[str, Any]:
    out: dict[str, Any] = {"role": msg.role.value, "content": msg.content}
    if msg.tool_call_id is not None:
        out["tool_call_id"] = msg.tool_call_id
    if msg.tool_name is not None:
        out["tool_name"] = msg.tool_name
    if msg.tool_calls:
        out["tool_calls"] = [
            {"tool_call_id": tc.tool_call_id, "name": tc.name, "arguments": tc.arguments}
            for tc in msg.tool_calls
        ]
    return out


def _planned_tool_call_descriptor(planned: PlannedToolCall) -> dict[str, Any]:
    return {
        "tool_execution_id": planned.tool_execution_id,
        "tool_name": planned.tool_name,
        "tool_call_id": planned.tool_call_id,
        "arguments_ref": planned.arguments_ref.to_dict(),
    }


def _planned_tool_call_from_descriptor(
    raw: dict[str, Any], *, read_artifact_text
) -> PlannedToolCall:
    tool_execution_id = str(raw.get("tool_execution_id") or "")
    tool_name = str(raw.get("tool_name") or "")
    tool_call_id = str(raw.get("tool_call_id") or "")
    args_ref_raw = raw.get("arguments_ref")
    if not tool_execution_id or not tool_name or not tool_call_id or not isinstance(args_ref_raw, dict):
        raise ValueError("Missing required tool call fields.")
    args_json = read_artifact_text(args_ref_raw)
    args_any = json.loads(args_json)
    if not isinstance(args_any, dict):
        raise ValueError("Tool arguments artifact is not a JSON object.")
    from .protocol import ArtifactRef as _ArtifactRef

    return PlannedToolCall(
        tool_execution_id=tool_execution_id,
        tool_name=tool_name,
        tool_call_id=tool_call_id,
        arguments=args_any,
        arguments_ref=_ArtifactRef.from_dict(args_ref_raw),
    )


def _tool_calls_from_payload(raw: Any, *, read_artifact_text) -> list[ToolCall]:
    if not isinstance(raw, list):
        return []
    out: list[ToolCall] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        tool_call_id = item.get("tool_call_id")
        name = item.get("tool_name") or item.get("name")
        args_ref_raw = item.get("arguments_ref")
        if not isinstance(tool_call_id, str) or not tool_call_id:
            continue
        if not isinstance(name, str) or not name:
            continue
        if not isinstance(args_ref_raw, dict):
            continue
        try:
            args_json = read_artifact_text(args_ref_raw)
            args_any = json.loads(args_json)
        except Exception:
            continue
        if not isinstance(args_any, dict):
            continue
        out.append(ToolCall(tool_call_id=tool_call_id, name=name, arguments=args_any, raw_arguments=None))
    return out


def _canonical_request_from_artifact_json(raw: str) -> CanonicalRequest:
    data = json.loads(raw)
    system = data.get("system")
    messages_raw = data.get("messages") or []
    if not isinstance(messages_raw, list):
        raise ValueError("messages must be a list")
    messages: list[CanonicalMessage] = []
    for item in messages_raw:
        if not isinstance(item, dict):
            continue
        role_raw = str(item.get("role") or "")
        try:
            role = CanonicalMessageRole(role_raw)
        except ValueError:
            continue
        messages.append(CanonicalMessage(role=role, content=str(item.get("content") or "")))
    params = data.get("params") or {}
    if not isinstance(params, dict):
        params = {}
    return CanonicalRequest(system=str(system) if system is not None else None, messages=messages, params=params)
