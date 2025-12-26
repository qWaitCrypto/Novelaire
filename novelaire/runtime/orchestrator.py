from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator

from .approval import ApprovalRecord, ApprovalStatus
from .error_codes import ErrorCode
from .agent_surface import SpecStatusSummary, build_agent_surface
from .event_bus import EventBus
from .ids import new_id, now_ts_ms
from .protocol import Event, EventKind, Op, OpKind
from .stores import ApprovalStore, ArtifactStore, EventLogStore, SessionStore

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
    ProjectListDirTool,
    ProjectGlobTool,
    ProjectReadTextManyTool,
    PlannedToolCall,
    ShellRunTool,
    SessionSearchTool,
    SessionExportTool,
    WebFetchTool,
    WebSearchTool,
    ProjectTextStatsTool,
    ProjectAIGCDetectTool,
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

from .orchestrator_approvals import (
    handle_approval_decision as _handle_approval_decision_impl,
    resume_from_approval as _resume_from_approval_impl,
    resume_tool_chain as _resume_tool_chain_impl,
)
from .orchestrator_chat_loop import continue_chat_operation as _continue_chat_operation_impl
from .orchestrator_compaction import (
    apply_memory_summary_retention as _apply_memory_summary_retention_impl,
    perform_compaction as _perform_compaction_impl,
)
from .orchestrator_llm import run_llm_complete as _run_llm_complete_impl, run_llm_stream as _run_llm_stream_impl
from .orchestrator_tool_loop import handle_planned_tool_calls as _handle_planned_tool_calls_impl
from .orchestrator_helpers import (
    _canonical_request_to_redacted_dict,
    _summarize_text,
    _tool_calls_from_payload,
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
        registry.register(ProjectListDirTool())
        registry.register(ProjectGlobTool())
        registry.register(ProjectReadTextManyTool())
        registry.register(ProjectTextStatsTool())
        registry.register(ProjectAIGCDetectTool())
        registry.register(ShellRunTool())
        registry.register(WebFetchTool())
        registry.register(WebSearchTool())
        registry.register(SessionSearchTool())
        registry.register(SessionExportTool())
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
        return _continue_chat_operation_impl(
            self,
            request_id=request_id,
            turn_id=turn_id,
            timeout_s=timeout_s,
            cancel=cancel,
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
        return _apply_memory_summary_retention_impl(self)

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
        return _perform_compaction_impl(
            self,
            trigger=trigger,
            request_id=request_id,
            turn_id=turn_id,
            timeout_s=timeout_s,
            cancel=cancel,
            context_stats=context_stats,
            threshold_ratio=threshold_ratio,
        )

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
        return _run_llm_stream_impl(
            self,
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
        return _run_llm_complete_impl(
            self,
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

    def _handle_planned_tool_calls(
        self,
        *,
        planned_calls: list[PlannedToolCall],
        request_id: str,
        turn_id: str | None,
        timeout_s: float | None,
        skip_approval_tool_execution_id: str | None,
    ) -> bool:
        return _handle_planned_tool_calls_impl(
            self,
            planned_calls=planned_calls,
            request_id=request_id,
            turn_id=turn_id,
            timeout_s=timeout_s,
            skip_approval_tool_execution_id=skip_approval_tool_execution_id,
        )

    def _handle_approval_decision(self, op: Op, *, timeout_s: float | None) -> None:
        return _handle_approval_decision_impl(self, op, timeout_s=timeout_s)

    def _resume_from_approval(self, record: ApprovalRecord, *, timeout_s: float | None) -> None:
        return _resume_from_approval_impl(self, record, timeout_s=timeout_s)

    def _resume_tool_chain(self, record: ApprovalRecord, *, timeout_s: float | None) -> None:
        return _resume_tool_chain_impl(self, record, timeout_s=timeout_s)

    def _read_artifact_text(self, ref_dict: dict[str, Any]) -> str:
        from .protocol import ArtifactRef

        ref = ArtifactRef.from_dict(ref_dict)
        data = self.artifact_store.get(ref)
        return data.decode("utf-8", errors="replace")
