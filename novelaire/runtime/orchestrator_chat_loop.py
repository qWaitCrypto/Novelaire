from __future__ import annotations

from typing import Any

from .context_mgmt import (
    approx_tokens_from_json,
    canonical_request_to_dict,
    compute_context_left_percent,
    resolve_context_limit_tokens,
)
from .compaction import settings_for_profile, should_auto_compact
from .error_codes import ErrorCode
from .ids import new_id
from .llm.errors import CancellationToken, ModelResolutionError
from .llm.types import CanonicalMessage, CanonicalMessageRole, ModelRequirements, ModelRole
from .protocol import EventKind, OpKind


def continue_chat_operation(
    orch,
    *,
    request_id: str,
    turn_id: str | None,
    timeout_s: float | None,
    cancel: CancellationToken | None,
) -> None:
    if orch._history is None:
        orch._history = []
    if orch.tool_registry is None or orch.tool_runtime is None:
        raise RuntimeError("Tool runtime not initialized.")

    guard_id = str(turn_id or request_id)

    for _turn_index in range(orch.max_tool_turns):
        while True:
            step_id = new_id("step")
            request = orch._build_request()
            requirements = ModelRequirements(
                needs_tools=bool(request.tools),
            )
            try:
                resolved = orch.model_router.resolve(role=ModelRole.MAIN, requirements=requirements)
            except ModelResolutionError as e:
                orch._emit(
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
                orch._emit(
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

            orch._emit(
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
                and guard_id not in orch._auto_compact_seen_turn_ids
                and should_auto_compact(
                    estimated_input_tokens=estimated_input_tokens,
                    context_limit_tokens=context_limit_tokens,
                    threshold_ratio=threshold_ratio,
                )
            ):
                orch._auto_compact_seen_turn_ids.add(guard_id)
                ok = orch._perform_compaction(
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

        context_ref = orch._write_context_ref(request)
        effective_timeout_s = timeout_s if timeout_s is not None else resolved.profile.timeout_s
        caps = resolved.profile.capabilities.with_provider_defaults(resolved.profile.provider_kind)
        use_streaming = caps.supports_streaming is True
        if use_streaming:
            response, planned_calls = orch._run_llm_stream(
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
            response, planned_calls = orch._run_llm_complete(
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

        orch._history.append(
            CanonicalMessage(
                role=CanonicalMessageRole.ASSISTANT,
                content=response.text,
                tool_calls=response.tool_calls or None,
            )
        )

        if not response.tool_calls:
            orch._emit(
                kind=EventKind.OPERATION_COMPLETED,
                payload={"op_kind": OpKind.CHAT.value},
                request_id=request_id,
                turn_id=turn_id,
            )
            return

        if not orch.tools_enabled:
            orch._emit(
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

        handled = orch._handle_planned_tool_calls(
            planned_calls=planned_calls,
            request_id=request_id,
            turn_id=turn_id,
            timeout_s=timeout_s,
            skip_approval_tool_execution_id=None,
        )
        if not handled:
            return

    orch._emit(
        kind=EventKind.OPERATION_FAILED,
        payload={
            "error": "Exceeded max tool turns for this operation.",
            "error_code": ErrorCode.TOOL_LOOP_LIMIT.value,
            "type": "tool_loop_limit",
        },
        request_id=request_id,
        turn_id=turn_id,
    )

