from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Iterable, Iterator

from .approval import ApprovalDecision, ApprovalRecord, ApprovalStatus
from .error_codes import ErrorCode
from .agent_surface import SpecStatusSummary, build_agent_surface
from .event_bus import EventBus
from .ids import new_id, now_ts_ms
from .protocol import Event, EventKind, Op, OpKind
from .stores import ApprovalStore, ArtifactStore, EventLogStore, SessionStore
from .context_mgmt import (
    approx_tokens_from_json,
    canonical_request_to_dict,
    compute_context_left_percent,
    resolve_context_limit_tokens,
)
from .compaction import (
    apply_compaction_retention,
    build_compaction_request,
    load_compact_prompt_text,
    settings_for_profile,
    should_auto_compact,
)

from .llm.client import LLMClient
from .llm.config import ModelConfig
from .llm.errors import CancellationToken, LLMRequestError, ModelResolutionError
from .llm.router import ModelRouter
from .llm.trace import LLMTrace
from .skills import SkillStore
from .plan import PlanStore
from .snapshots import GitSnapshotBackend
from .spec_workflow import SpecProposalStore, SpecStateStore, SpecStore
from .llm.types import (
    CanonicalMessage,
    CanonicalMessageRole,
    CanonicalRequest,
    ModelRequirements,
    ModelRole,
    ProviderKind,
    ToolCall,
    ToolSpec,
)
from .tools import (
    InspectionDecision,
    ProjectReadTextTool,
    ProjectSearchTextTool,
    ProjectTextEditorTool,
    ProjectWriteTextTool,
    PlannedToolCall,
    ShellRunTool,
    SkillListTool,
    SkillLoadTool,
    SkillReadFileTool,
    UpdatePlanTool,
    SpecQueryTool,
    SpecGetTool,
    SpecProposeTool,
    SpecApplyTool,
    SpecSealTool,
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
    model_config: ModelConfig
    llm_client: LLMClient
    model_router: ModelRouter
    skill_store: SkillStore | None = None
    plan_store: PlanStore | None = None
    spec_store: SpecStore | None = None
    spec_state_store: SpecStateStore | None = None
    spec_proposal_store: SpecProposalStore | None = None
    snapshot_backend: GitSnapshotBackend | None = None
    tools_enabled: bool = False
    max_tool_turns: int = 30
    tool_registry: ToolRegistry | None = None
    tool_runtime: ToolRuntime | None = None
    system_prompt: str | None = None
    memory_summary: str | None = None
    _history: list[CanonicalMessage] | None = None
    _auto_compact_seen_turn_ids: set[str] = field(default_factory=set)
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
        max_tool_turns: int | None = None,
    ) -> "Orchestrator":
        effective_system_prompt = DEFAULT_SYSTEM_PROMPT if system_prompt is None else system_prompt
        effective_max_tool_turns = 30 if max_tool_turns is None else int(max_tool_turns)
        if effective_max_tool_turns < 1:
            raise ValueError("max_tool_turns must be >= 1")
        if effective_max_tool_turns > 256:
            raise ValueError("max_tool_turns must be <= 256")
        router = ModelRouter(model_config)
        skill_store = SkillStore(project_root=project_root)
        plan_store = PlanStore(session_store=session_store, session_id=session_id)
        spec_store = SpecStore(project_root=project_root)
        spec_state_store = SpecStateStore(project_root=project_root)
        spec_proposal_store = SpecProposalStore(project_root=project_root)
        snapshot_backend = GitSnapshotBackend(project_root=project_root)
        registry = ToolRegistry()
        registry.register(ProjectReadTextTool())
        registry.register(ProjectWriteTextTool())
        registry.register(ProjectTextEditorTool())
        registry.register(ProjectSearchTextTool())
        registry.register(ShellRunTool())
        registry.register(SkillListTool(skill_store))
        registry.register(SkillLoadTool(skill_store))
        registry.register(SkillReadFileTool(skill_store))
        registry.register(UpdatePlanTool(plan_store))
        registry.register(SpecQueryTool(spec_store))
        registry.register(SpecGetTool(spec_store))
        registry.register(SpecProposeTool(spec_store, spec_proposal_store, spec_state_store, artifact_store))
        registry.register(SpecApplyTool(spec_proposal_store, spec_state_store))
        registry.register(SpecSealTool(spec_state_store, snapshot_backend))
        tool_runtime = ToolRuntime(project_root=project_root, registry=registry, artifact_store=artifact_store)
        return Orchestrator(
            project_root=project_root,
            session_id=session_id,
            event_bus=event_bus,
            session_store=session_store,
            event_log_store=event_log_store,
            artifact_store=artifact_store,
            approval_store=approval_store,
            model_config=model_config,
            llm_client=LLMClient(model_config),
            model_router=router,
            skill_store=skill_store,
            plan_store=plan_store,
            spec_store=spec_store,
            spec_state_store=spec_state_store,
            spec_proposal_store=spec_proposal_store,
            snapshot_backend=snapshot_backend,
            tools_enabled=tools_enabled,
            max_tool_turns=effective_max_tool_turns,
            tool_registry=registry,
            tool_runtime=tool_runtime,
            system_prompt=effective_system_prompt,
            _history=[],
        )

    def set_chat_model_profile(self, profile_id: str) -> None:
        """
        Switch the active chat model (ModelRole.MAIN) to a different configured profile.

        This updates the router and client for subsequent requests.
        """

        if profile_id not in self.model_config.profiles:
            raise ValueError(f"Unknown model profile: {profile_id}")
        cfg = ModelConfig(
            profiles=dict(self.model_config.profiles),
            role_pointers={ModelRole.MAIN: profile_id},
        )
        cfg.validate_consistency()
        self.model_config = cfg
        self.model_router = ModelRouter(cfg)
        self.llm_client = LLMClient(cfg)

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
        if op.kind == OpKind.COMPACT.value:
            self._handle_compact(op, timeout_s=timeout_s, cancel=cancel)
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

    def _handle_compact(
        self,
        op: Op,
        *,
        timeout_s: float | None,
        cancel: CancellationToken | None = None,
    ) -> None:
        cancel = cancel or CancellationToken()
        ok = self._perform_compaction(
            trigger="manual",
            request_id=op.request_id,
            turn_id=op.turn_id,
            timeout_s=timeout_s,
            cancel=cancel,
        )
        if not ok:
            return

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

        guard_id = str(turn_id or request_id)

        for turn_index in range(self.max_tool_turns):
            while True:
                step_id = new_id("step")
                request = self._build_request()
                requirements = ModelRequirements(
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

                context_limit_tokens = resolve_context_limit_tokens(
                    resolved.profile.limits.context_limit_tokens if resolved.profile.limits is not None else None
                )

                estimated_input_tokens = approx_tokens_from_json(canonical_request_to_dict(request))
                context_stats: dict[str, Any] = {
                    "estimated_input_tokens": estimated_input_tokens,
                    "estimate_kind": "bytes_per_token_4",
                    "context_limit_tokens": context_limit_tokens,
                }
                if isinstance(context_limit_tokens, int) and context_limit_tokens > 0:
                    context_stats["estimated_context_left_percent"] = compute_context_left_percent(
                        used_tokens=estimated_input_tokens,
                        context_limit_tokens=context_limit_tokens,
                    )

                cm = settings_for_profile(resolved.profile)
                threshold_ratio = cm.auto_compact_threshold_ratio
                if (
                    guard_id
                    and guard_id not in self._auto_compact_seen_turn_ids
                    and should_auto_compact(
                        estimated_input_tokens=estimated_input_tokens,
                        context_limit_tokens=context_limit_tokens,
                        threshold_ratio=threshold_ratio,
                    )
                ):
                    self._auto_compact_seen_turn_ids.add(guard_id)
                    ok = self._perform_compaction(
                        trigger="auto",
                        request_id=request_id,
                        turn_id=turn_id,
                        timeout_s=timeout_s,
                        cancel=cancel,
                        context_stats=context_stats,
                        threshold_ratio=threshold_ratio,
                    )
                    if not ok:
                        return
                    continue

                break

            context_ref = self._write_context_ref(request)
            effective_timeout_s = timeout_s if timeout_s is not None else resolved.profile.timeout_s
            caps = resolved.profile.capabilities.with_provider_defaults(resolved.profile.provider_kind)
            use_streaming = caps.supports_streaming is True
            if use_streaming:
                response, planned_calls = self._run_llm_stream(
                    request=request,
                    context_ref=context_ref.to_dict(),
                    context_stats=context_stats,
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
                    context_stats=context_stats,
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
        tools: list[ToolSpec] = []
        if self.tools_enabled and self.tool_registry is not None:
            tools = self.tool_registry.list_specs()

        skills = self.skill_store.list() if self.skill_store is not None else []
        plan = self.plan_store.get().plan if self.plan_store is not None else []

        spec_summary = SpecStatusSummary(status="open")
        if self.spec_state_store is not None:
            state = self.spec_state_store.get()
            spec_summary = SpecStatusSummary(status=state.status, label=state.label)

        surface = build_agent_surface(
            tools=tools,
            skills=skills,
            plan=plan,
            spec=spec_summary,
        )

        base_system = self.system_prompt or DEFAULT_SYSTEM_PROMPT
        parts = [base_system]
        if isinstance(self.memory_summary, str) and self.memory_summary.strip():
            parts.append("Session memory summary:\n\n" + self.memory_summary.strip())
        parts.append(surface)
        system = "\n\n".join(parts)
        return CanonicalRequest(system=system, messages=list(self._history or []), tools=tools)

    def apply_memory_summary_retention(self) -> None:
        """
        Best-effort pruning of loaded history when resuming a session that already has a memory summary.

        This keeps event logs append-only while ensuring resumed prompts do not re-send the full transcript.
        """

        if self._history is None:
            self._history = []
        if not (isinstance(self.memory_summary, str) and self.memory_summary.strip()):
            return
        profile = self.model_config.get_profile_for_role(ModelRole.MAIN)
        if profile is None:
            return
        cm = settings_for_profile(profile)
        context_limit_tokens = resolve_context_limit_tokens(
            profile.limits.context_limit_tokens if profile.limits is not None else None
        )
        retained = apply_compaction_retention(
            history=list(self._history),
            memory_summary=self.memory_summary.strip(),
            context_limit_tokens=context_limit_tokens,
            history_budget_ratio=cm.history_budget_ratio,
            history_budget_fallback_tokens=cm.history_budget_fallback_tokens,
        )
        self.memory_summary = retained.memory_summary
        self._history = list(retained.retained_history)

    def _perform_compaction(
        self,
        *,
        trigger: str,
        request_id: str,
        turn_id: str | None,
        timeout_s: float | None,
        cancel: CancellationToken | None,
        context_stats: dict[str, Any] | None = None,
        threshold_ratio: float | None = None,
    ) -> bool:
        cancel = cancel or CancellationToken()
        if self._history is None:
            self._history = []

        is_auto = trigger == "auto"
        has_summary = isinstance(self.memory_summary, str) and self.memory_summary.strip()
        if not self._history and not has_summary:
            self._emit(
                kind=EventKind.OPERATION_FAILED,
                payload={
                    "op_kind": OpKind.COMPACT.value,
                    "error": "Nothing to compact (empty history).",
                    "error_code": ErrorCode.BAD_REQUEST.value,
                    "type": "compact_empty",
                },
                request_id=request_id,
                turn_id=turn_id,
            )
            return False

        profile = self.model_config.get_profile_for_role(ModelRole.MAIN)
        if profile is None:
            self._emit(
                kind=EventKind.OPERATION_FAILED,
                payload={
                    "op_kind": OpKind.COMPACT.value,
                    "error": "No active chat model configured.",
                    "error_code": ErrorCode.MODEL_RESOLUTION.value,
                    "type": "compact_no_model",
                },
                request_id=request_id,
                turn_id=turn_id,
            )
            return False

        step_id = new_id("step")
        self._emit(
            kind=EventKind.OPERATION_STARTED,
            payload={"op_kind": OpKind.COMPACT.value, "trigger": trigger},
            request_id=request_id,
            turn_id=turn_id,
            step_id=step_id,
        )

        cm = settings_for_profile(profile)
        prompt_text = load_compact_prompt_text()
        compact_request = build_compaction_request(
            history=list(self._history),
            memory_summary=self.memory_summary if has_summary else None,
            prompt_text=prompt_text,
            tool_output_budget_tokens=cm.tool_output_budget_tokens,
        )

        extra: dict[str, Any] = {}
        if isinstance(context_stats, dict):
            extra["pre_context_stats"] = dict(context_stats)
        if is_auto and threshold_ratio is not None:
            extra["threshold_ratio"] = float(threshold_ratio)
        self._emit(
            kind=EventKind.OPERATION_PROGRESS,
            payload={
                "op_kind": OpKind.COMPACT.value,
                "status": "running",
                "trigger": trigger,
                "message": "Compacting…",
                "details": extra,
            },
            request_id=request_id,
            turn_id=turn_id,
            step_id=step_id,
        )

        trace = LLMTrace.maybe_create(
            project_root=self.project_root,
            session_id=self.session_id,
            request_id=request_id,
            turn_id=turn_id,
            step_id=step_id,
        )
        if trace is not None:
            trace.record_meta(profile_id=profile.profile_id, operation="compact")
        effective_timeout_s = timeout_s if timeout_s is not None else profile.timeout_s

        try:
            response = self.llm_client.complete(
                role=ModelRole.MAIN,
                requirements=ModelRequirements(needs_streaming=False, needs_tools=False),
                request=compact_request,
                timeout_s=effective_timeout_s,
                cancel=cancel,
                trace=trace,
            )
        except LLMRequestError as e:
            if trace is not None:
                if e.code is ErrorCode.CANCELLED:
                    trace.record_cancelled(reason="cancelled", code=ErrorCode.CANCELLED.value)
                else:
                    trace.record_error(e, code=e.code.value if e.code is not None else None)
            if e.code is ErrorCode.CANCELLED:
                self._emit(
                    kind=EventKind.OPERATION_CANCELLED,
                    payload={
                        "op_kind": OpKind.COMPACT.value,
                        "error_code": ErrorCode.CANCELLED.value,
                        "reason": "cancelled",
                        "phase": "compact",
                    },
                    request_id=request_id,
                    turn_id=turn_id,
                    step_id=step_id,
                )
                return False
            self._emit(
                kind=EventKind.OPERATION_FAILED,
                payload={
                    "op_kind": OpKind.COMPACT.value,
                    "error": str(e),
                    "error_code": e.code.value,
                    "type": "compact_llm_request",
                },
                request_id=request_id,
                turn_id=turn_id,
                step_id=step_id,
            )
            return False

        summary_text = response.text or ""
        if not summary_text.strip():
            self._emit(
                kind=EventKind.OPERATION_FAILED,
                payload={
                    "op_kind": OpKind.COMPACT.value,
                    "error": "Compaction produced empty summary.",
                    "error_code": ErrorCode.RESPONSE_VALIDATION.value,
                    "type": "compact_empty_summary",
                },
                request_id=request_id,
                turn_id=turn_id,
                step_id=step_id,
            )
            return False

        usage = response.usage.__dict__ if response.usage is not None else None
        raw_summary_ref = self.artifact_store.put(
            summary_text,
            kind="chat_compact_summary_raw",
            meta={"summary": _summarize_text(summary_text)},
        )

        context_limit_tokens = resolve_context_limit_tokens(
            profile.limits.context_limit_tokens if profile.limits is not None else None
        )

        before_count = len(self._history)
        retained = apply_compaction_retention(
            history=list(self._history),
            memory_summary=summary_text.strip(),
            context_limit_tokens=context_limit_tokens,
            history_budget_ratio=cm.history_budget_ratio,
            history_budget_fallback_tokens=cm.history_budget_fallback_tokens,
        )
        used_summary = retained.memory_summary
        used_summary_ref = self.artifact_store.put(
            used_summary,
            kind="chat_memory_summary",
            meta={"summary": _summarize_text(used_summary)},
        )
        self.memory_summary = used_summary
        self._history = list(retained.retained_history)

        snapshot_ref = self.artifact_store.put(
            json.dumps(
                {
                    "trigger": trigger,
                    "raw_summary_ref": raw_summary_ref.to_dict(),
                    "memory_summary_ref": used_summary_ref.to_dict(),
                    "summary_truncated": used_summary.strip() != summary_text.strip(),
                    "history_before_count": before_count,
                    "history_after_count": len(self._history),
                    "history_budget_tokens": retained.history_budget_tokens,
                    "summary_estimated_tokens": retained.summary_estimated_tokens,
                    "usage": usage,
                },
                ensure_ascii=False,
            ),
            kind="chat_compact_snapshot",
            meta={"summary": "Compaction snapshot"},
        )

        try:
            patch: dict[str, Any] = {
                "memory_summary": self.memory_summary,
                "memory_summary_ref": used_summary_ref.to_dict(),
                "last_compact_at": now_ts_ms(),
            }
            if isinstance(usage, dict):
                patch["last_compaction_usage"] = usage
            self.session_store.update_session(self.session_id, patch)
        except Exception:
            pass

        post_request = self._build_request()
        post_estimated_input_tokens = approx_tokens_from_json(canonical_request_to_dict(post_request))
        post_stats: dict[str, Any] = {
            "estimated_input_tokens": post_estimated_input_tokens,
            "estimate_kind": "bytes_per_token_4",
            "context_limit_tokens": context_limit_tokens,
        }
        if isinstance(context_limit_tokens, int) and context_limit_tokens > 0:
            post_stats["estimated_context_left_percent"] = compute_context_left_percent(
                used_tokens=post_estimated_input_tokens,
                context_limit_tokens=context_limit_tokens,
            )

        self._emit(
            kind=EventKind.OPERATION_COMPLETED,
            payload={
                "op_kind": OpKind.COMPACT.value,
                "trigger": trigger,
                "raw_summary_ref": raw_summary_ref.to_dict(),
                "summary_ref": used_summary_ref.to_dict(),
                "snapshot_ref": snapshot_ref.to_dict(),
                "history_before_count": before_count,
                "history_after_count": len(self._history),
                "history_budget_tokens": retained.history_budget_tokens,
                "summary_estimated_tokens": retained.summary_estimated_tokens,
                "context_stats": post_stats,
            },
            request_id=request_id,
            turn_id=turn_id,
            step_id=step_id,
        )
        return True

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
            project_root=self.project_root,
            session_id=self.session_id,
            request_id=request_id,
            turn_id=turn_id,
            step_id=step_id,
        )
        if trace is not None:
            trace.record_meta(profile_id=profile_id, context_ref=context_ref, operation="stream")
        stream_iter = None
        self._emit(
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
            stream_iter = self.llm_client.stream(
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
        except KeyboardInterrupt as e:
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
                if trace is not None:
                    trace.record_cancelled(reason="cancelled", code=ErrorCode.CANCELLED.value)
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
                        "details": e.details,
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

            # Best-effort fallback: some OpenAI-compatible gateways claim streaming support
            # but frequently terminate the TLS connection (e.g. SSLEOFError) before the first chunk.
            # If we haven't emitted any output yet, retry once using non-streaming complete().
            if (
                e.code is ErrorCode.NETWORK_ERROR
                and not streamed_parts
                and not delta_buf
            ):
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
                        "details": e.details,
                        "handled": "fallback_to_complete",
                    },
                    request_id=request_id,
                    turn_id=turn_id,
                    step_id=step_id,
                )
                self._emit(
                    kind=EventKind.OPERATION_PROGRESS,
                    payload={"message": "Streaming failed; retrying without streaming."},
                    request_id=request_id,
                    turn_id=turn_id,
                    step_id=step_id,
                )
                return self._run_llm_complete(
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
                    "details": e.details,
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
            if trace is not None:
                trace.record_error(e, code=ErrorCode.MODEL_RESOLUTION.value)
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
            if trace is not None:
                trace.record_error(RuntimeError("LLM stream ended without a completed response."), code=ErrorCode.RESPONSE_VALIDATION.value)
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
                "context_stats": merged_stats,
                "stop_reason": final_response.stop_reason,
            },
            request_id=request_id,
            turn_id=turn_id,
            step_id=step_id,
        )

        if isinstance(usage, dict):
            try:
                self.session_store.update_session(
                    self.session_id,
                    {
                        "last_usage": usage,
                        "last_context_stats": merged_stats,
                    },
                )
            except Exception:
                pass

        if trace is not None:
            trace.record_response(final_response)
        return final_response, planned_calls

    def _run_llm_complete(
        self,
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
            project_root=self.project_root,
            session_id=self.session_id,
            request_id=request_id,
            turn_id=turn_id,
            step_id=step_id,
        )
        if trace is not None:
            trace.record_meta(profile_id=profile_id, context_ref=context_ref, operation="complete")
        self._emit(
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

        try:
            final_response = self.llm_client.complete(
                role=ModelRole.MAIN,
                requirements=ModelRequirements(needs_streaming=False, needs_tools=bool(request.tools)),
                request=request,
                timeout_s=timeout_s,
                cancel=cancel,
                trace=trace,
            )
        except LLMRequestError as e:
            if trace is not None:
                if e.code is ErrorCode.CANCELLED:
                    trace.record_cancelled(reason="cancelled", code=ErrorCode.CANCELLED.value)
                else:
                    trace.record_error(e, code=e.code.value if e.code is not None else None)
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
                    "details": e.details,
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
                "context_stats": merged_stats,
                "stop_reason": final_response.stop_reason,
                "stream": False,
            },
            request_id=request_id,
            turn_id=turn_id,
            step_id=step_id,
        )

        if isinstance(usage, dict):
            try:
                self.session_store.update_session(
                    self.session_id,
                    {
                        "last_usage": usage,
                        "last_context_stats": merged_stats,
                    },
                )
            except Exception:
                pass

        if trace is not None:
            trace.record_response(final_response)
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
            ui_summary = _summarize_tool_for_ui(planned.tool_name, planned.arguments)
            inspection = self.tool_runtime.inspect(planned)
            if inspection.decision is InspectionDecision.DENY:
                code = inspection.error_code or ErrorCode.TOOL_DENIED
                self._emit(
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
                        "summary": ui_summary,
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
                    "summary": ui_summary,
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

            if result.status == "succeeded" and result.tool_name == "update_plan" and self.plan_store is not None:
                state = self.plan_store.get()
                self._emit(
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
                    summary = None
                    try:
                        planned = _planned_tool_call_from_descriptor(first, read_artifact_text=self._read_artifact_text)
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
                        self._emit(
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


def _summarize_tool_for_ui(tool_name: str, arguments: dict[str, Any]) -> str:
    def _q(s: str) -> str:
        # Quote without backticks so terminals that don't render markdown still look OK.
        return f'"{s}"'

    if tool_name == "project__read_text":
        path = arguments.get("path")
        if isinstance(path, str) and path:
            return f"Read {_q(path)}"
        return "Read file"

    if tool_name == "project__search_text":
        query = arguments.get("query")
        path = arguments.get("path")
        if isinstance(query, str) and query:
            if isinstance(path, str) and path:
                return f"Search {_q(query)} in {_q(path)}"
            return f"Search {_q(query)}"
        return "Search text"

    if tool_name == "project__write_text":
        path = arguments.get("path")
        if isinstance(path, str) and path:
            return f'Write {_q(path)}'
        return "Write file"

    if tool_name == "project__text_editor":
        command = arguments.get("command")
        path = arguments.get("path")
        if isinstance(command, str) and isinstance(path, str) and path:
            return f"Edit {_q(path)} ({command})"
        if isinstance(path, str) and path:
            return f"Edit {_q(path)}"
        return "Edit file"

    if tool_name == "shell__run":
        command = arguments.get("command")
        if isinstance(command, str) and command.strip():
            one_line = " ".join(command.strip().splitlines()).strip()
            if len(one_line) > 80:
                one_line = one_line[:79] + "…"
            return f"Run $ {one_line}"
        return "Run shell command"

    if tool_name == "update_plan":
        return "Update plan"

    if tool_name.startswith("skill__"):
        name = arguments.get("name")
        if isinstance(name, str) and name:
            return f"Skill {tool_name} ({_q(name)})"
        return f"Skill {tool_name}"

    if tool_name.startswith("spec__"):
        if tool_name == "spec__apply":
            proposal_id = arguments.get("proposal_id")
            if isinstance(proposal_id, str) and proposal_id:
                return f"Spec apply ({_q(proposal_id)})"
            return "Spec apply"
        if tool_name == "spec__seal":
            label = arguments.get("label")
            if isinstance(label, str) and label:
                return f"Spec seal ({_q(label)})"
            return "Spec seal"
        return f"Spec {tool_name}"

    return tool_name


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
