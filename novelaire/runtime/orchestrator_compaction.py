from __future__ import annotations

import json
from typing import Any

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
)
from .error_codes import ErrorCode
from .ids import new_id, now_ts_ms
from .llm.errors import CancellationToken, LLMRequestError
from .llm.trace import LLMTrace
from .llm.types import ModelRequirements, ModelRole
from .protocol import EventKind, OpKind
from .orchestrator_helpers import _summarize_text


def apply_memory_summary_retention(orch) -> None:
    """
    Best-effort pruning of loaded history when resuming a session that already has a memory summary.

    This keeps event logs append-only while ensuring resumed prompts do not re-send the full transcript.
    """

    if orch._history is None:
        orch._history = []
    if not (isinstance(orch.memory_summary, str) and orch.memory_summary.strip()):
        return
    profile = orch.model_config.get_profile_for_role(ModelRole.MAIN)
    if profile is None:
        return
    cm = settings_for_profile(profile)
    context_limit_tokens = resolve_context_limit_tokens(
        profile.limits.context_limit_tokens if profile.limits is not None else None
    )
    retained = apply_compaction_retention(
        history=list(orch._history),
        memory_summary=orch.memory_summary.strip(),
        context_limit_tokens=context_limit_tokens,
        history_budget_ratio=cm.history_budget_ratio,
        history_budget_fallback_tokens=cm.history_budget_fallback_tokens,
    )
    orch.memory_summary = retained.memory_summary
    orch._history = list(retained.retained_history)


def perform_compaction(
    orch,
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
    if orch._history is None:
        orch._history = []

    is_auto = trigger == "auto"
    has_summary = isinstance(orch.memory_summary, str) and orch.memory_summary.strip()
    if not orch._history and not has_summary:
        orch._emit(
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

    profile = orch.model_config.get_profile_for_role(ModelRole.MAIN)
    if profile is None:
        orch._emit(
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
    orch._emit(
        kind=EventKind.OPERATION_STARTED,
        payload={"op_kind": OpKind.COMPACT.value, "trigger": trigger},
        request_id=request_id,
        turn_id=turn_id,
        step_id=step_id,
    )

    cm = settings_for_profile(profile)
    prompt_text = load_compact_prompt_text()
    compact_request = build_compaction_request(
        history=list(orch._history),
        memory_summary=orch.memory_summary if has_summary else None,
        prompt_text=prompt_text,
        tool_output_budget_tokens=cm.tool_output_budget_tokens,
    )

    extra: dict[str, Any] = {}
    if isinstance(context_stats, dict):
        extra["pre_context_stats"] = dict(context_stats)
    if is_auto and threshold_ratio is not None:
        extra["threshold_ratio"] = float(threshold_ratio)
    orch._emit(
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
        project_root=orch.project_root,
        session_id=orch.session_id,
        request_id=request_id,
        turn_id=turn_id,
        step_id=step_id,
    )
    if trace is not None:
        trace.record_meta(profile_id=profile.profile_id, operation="compact")
    effective_timeout_s = timeout_s if timeout_s is not None else profile.timeout_s

    try:
        response = orch.llm_client.complete(
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
            orch._emit(
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
        orch._emit(
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
        orch._emit(
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
    raw_summary_ref = orch.artifact_store.put(
        summary_text,
        kind="chat_compact_summary_raw",
        meta={"summary": _summarize_text(summary_text)},
    )

    context_limit_tokens = resolve_context_limit_tokens(
        profile.limits.context_limit_tokens if profile.limits is not None else None
    )

    before_count = len(orch._history)
    retained = apply_compaction_retention(
        history=list(orch._history),
        memory_summary=summary_text.strip(),
        context_limit_tokens=context_limit_tokens,
        history_budget_ratio=cm.history_budget_ratio,
        history_budget_fallback_tokens=cm.history_budget_fallback_tokens,
    )
    used_summary = retained.memory_summary
    used_summary_ref = orch.artifact_store.put(
        used_summary,
        kind="chat_memory_summary",
        meta={"summary": _summarize_text(used_summary)},
    )
    orch.memory_summary = used_summary
    orch._history = list(retained.retained_history)

    snapshot_ref = orch.artifact_store.put(
        json.dumps(
            {
                "trigger": trigger,
                "raw_summary_ref": raw_summary_ref.to_dict(),
                "memory_summary_ref": used_summary_ref.to_dict(),
                "summary_truncated": used_summary.strip() != summary_text.strip(),
                "history_before_count": before_count,
                "history_after_count": len(orch._history),
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
            "memory_summary": orch.memory_summary,
            "memory_summary_ref": used_summary_ref.to_dict(),
            "last_compact_at": now_ts_ms(),
        }
        if isinstance(usage, dict):
            patch["last_compaction_usage"] = usage
        orch.session_store.update_session(orch.session_id, patch)
    except Exception:
        pass

    post_request = orch._build_request()
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

    orch._emit(
        kind=EventKind.OPERATION_COMPLETED,
        payload={
            "op_kind": OpKind.COMPACT.value,
            "trigger": trigger,
            "raw_summary_ref": raw_summary_ref.to_dict(),
            "summary_ref": used_summary_ref.to_dict(),
            "snapshot_ref": snapshot_ref.to_dict(),
            "history_before_count": before_count,
            "history_after_count": len(orch._history),
            "history_budget_tokens": retained.history_budget_tokens,
            "summary_estimated_tokens": retained.summary_estimated_tokens,
            "context_stats": post_stats,
        },
        request_id=request_id,
        turn_id=turn_id,
        step_id=step_id,
    )
    return True

