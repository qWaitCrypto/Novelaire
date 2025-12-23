from __future__ import annotations

import json
import time
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from ..protocol import ArtifactRef
from ..error_codes import ErrorCode

from ..stores import ArtifactStore
from .registry import ToolRegistry


class ToolRuntimeError(RuntimeError):
    pass


class InspectionDecision(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_APPROVAL = "require_approval"


class ToolApprovalMode(StrEnum):
    """
    Tool approval policy for a session.

    - strict: require approval for every tool call (including reads/search).
    - standard: require approval only for high-risk tool calls (default).
    - trusted: never require approval (dangerous).
    """

    STRICT = "strict"
    STANDARD = "standard"
    TRUSTED = "trusted"


@dataclass(frozen=True, slots=True)
class InspectionResult:
    decision: InspectionDecision
    action_summary: str
    risk_level: str | None = None
    reason: str | None = None
    error_code: ErrorCode | None = None
    diff_ref: ArtifactRef | None = None


@dataclass(frozen=True, slots=True)
class PlannedToolCall:
    tool_execution_id: str
    tool_call_id: str
    tool_name: str
    arguments: dict[str, Any]
    arguments_ref: ArtifactRef


@dataclass(frozen=True, slots=True)
class ToolExecutionResult:
    tool_execution_id: str
    tool_call_id: str
    tool_name: str
    status: str
    output_ref: ArtifactRef | None
    tool_message_ref: ArtifactRef | None
    tool_message_content: str | None
    duration_ms: int
    error_code: ErrorCode | None = None
    error: str | None = None


class ToolRuntime:
    def __init__(
        self,
        *,
        project_root: Path,
        registry: ToolRegistry,
        artifact_store: ArtifactStore,
        approval_mode: ToolApprovalMode = ToolApprovalMode.STANDARD,
    ) -> None:
        self._project_root = project_root.expanduser().resolve()
        self._registry = registry
        self._artifact_store = artifact_store
        self._approval_mode = approval_mode

    def set_approval_mode(self, mode: ToolApprovalMode) -> None:
        self._approval_mode = mode

    def get_approval_mode(self) -> ToolApprovalMode:
        return self._approval_mode

    def plan(self, *, tool_execution_id: str, tool_name: str, tool_call_id: str, arguments: dict[str, Any]) -> PlannedToolCall:
        if not tool_call_id:
            raise ToolRuntimeError("Tool call is missing tool_call_id; cannot return tool_result.")
        if not tool_name:
            raise ToolRuntimeError("Tool call is missing tool name.")
        if not isinstance(arguments, dict):
            raise ToolRuntimeError("Tool call arguments must be an object.")

        args_ref = self._artifact_store.put(
            json.dumps(arguments, ensure_ascii=False, sort_keys=True, indent=2),
            kind="tool_args",
            meta={"summary": f"{tool_name} args"},
        )
        return PlannedToolCall(
            tool_execution_id=tool_execution_id,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            arguments=arguments,
            arguments_ref=args_ref,
        )

    def inspect(self, planned: PlannedToolCall) -> InspectionResult:
        tool = self._registry.get(planned.tool_name)
        if tool is None:
            return InspectionResult(
                decision=InspectionDecision.DENY,
                action_summary=f"Unknown tool: {planned.tool_name}",
                risk_level="high",
                reason="Tool is not registered.",
                error_code=ErrorCode.TOOL_UNKNOWN,
            )

        if self._approval_mode is ToolApprovalMode.TRUSTED:
            return InspectionResult(
                decision=InspectionDecision.ALLOW,
                action_summary=f"Execute tool: {planned.tool_name}",
                risk_level="high",
                reason="Approval mode is trusted (auto-allow).",
                error_code=None,
                diff_ref=None,
            )

        if self._approval_mode is ToolApprovalMode.STRICT:
            return self._inspect_strict(planned)

        if planned.tool_name == "shell__run":
            try:
                diff_ref = self._build_shell_run_preview(planned)
            except Exception as e:
                code = _classify_tool_exception(e)
                return InspectionResult(
                    decision=InspectionDecision.DENY,
                    action_summary="Invalid shell command request.",
                    risk_level="high",
                    reason=str(e),
                    error_code=code,
                    diff_ref=None,
                )
            return InspectionResult(
                decision=InspectionDecision.REQUIRE_APPROVAL,
                action_summary="Run shell command",
                risk_level="high",
                reason="Shell commands can modify files and system state.",
                error_code=None,
                diff_ref=diff_ref,
            )

        return InspectionResult(
            decision=InspectionDecision.ALLOW,
            action_summary=f"Execute tool: {planned.tool_name}",
            risk_level="low",
            reason=None,
            error_code=None,
            diff_ref=None,
        )

    def execute(self, planned: PlannedToolCall) -> ToolExecutionResult:
        tool = self._registry.get(planned.tool_name)
        started = time.monotonic()
        if tool is None:
            duration_ms = int((time.monotonic() - started) * 1000)
            return ToolExecutionResult(
                tool_execution_id=planned.tool_execution_id,
                tool_call_id=planned.tool_call_id,
                tool_name=planned.tool_name,
                status="failed",
                output_ref=None,
                tool_message_ref=None,
                tool_message_content=None,
                duration_ms=duration_ms,
                error_code=ErrorCode.TOOL_UNKNOWN,
                error=f"Unknown tool: {planned.tool_name}",
            )

        try:
            raw = tool.execute(args=planned.arguments, project_root=self._project_root)
        except Exception as e:
            duration_ms = int((time.monotonic() - started) * 1000)
            return ToolExecutionResult(
                tool_execution_id=planned.tool_execution_id,
                tool_call_id=planned.tool_call_id,
                tool_name=planned.tool_name,
                status="failed",
                output_ref=None,
                tool_message_ref=None,
                tool_message_content=None,
                duration_ms=duration_ms,
                error_code=_classify_tool_exception(e),
                error=str(e),
            )

        duration_ms = int((time.monotonic() - started) * 1000)
        output_ref = self._artifact_store.put(
            json.dumps(raw, ensure_ascii=False, sort_keys=True, indent=2),
            kind="tool_output",
            meta={"summary": f"{planned.tool_name} output"},
        )

        tool_message = json.dumps(
            {
                "ok": True,
                "tool": planned.tool_name,
                "output_ref": output_ref.to_dict(),
                "result": raw,
            },
            ensure_ascii=False,
        )
        tool_message_ref = self._artifact_store.put(
            tool_message,
            kind="tool_message",
            meta={"summary": f"{planned.tool_name} tool_result"},
        )
        return ToolExecutionResult(
            tool_execution_id=planned.tool_execution_id,
            tool_call_id=planned.tool_call_id,
            tool_name=planned.tool_name,
            status="succeeded",
            output_ref=output_ref,
            tool_message_ref=tool_message_ref,
            tool_message_content=tool_message,
            duration_ms=duration_ms,
            error_code=None,
            error=None,
        )

    def _build_write_text_diff(self, planned: PlannedToolCall) -> ArtifactRef:
        from difflib import unified_diff

        path = planned.arguments.get("path")
        content = planned.arguments.get("content")
        mode = planned.arguments.get("mode") or "overwrite"
        if not isinstance(path, str) or not path:
            raise ValueError("project__write_text: missing path")
        if not isinstance(content, str):
            raise ValueError("project__write_text: missing content")
        if mode not in ("overwrite", "append"):
            raise ValueError("project__write_text: invalid mode")

        target = (self._project_root / Path(path)).resolve()
        project_root = self._project_root.resolve()
        if target != project_root and project_root not in target.parents:
            raise PermissionError("project__write_text: path escapes project root")

        old = ""
        if target.exists() and target.is_file():
            old = target.read_text(encoding="utf-8", errors="replace")
        new = old + content if mode == "append" and target.exists() else content

        diff_lines = list(
            unified_diff(
                old.splitlines(keepends=True),
                new.splitlines(keepends=True),
                fromfile=f"a/{path}",
                tofile=f"b/{path}",
            )
        )
        diff_text = "".join(diff_lines) or "(no diff)"
        return self._artifact_store.put(
            diff_text,
            kind="diff",
            meta={"summary": f"Diff for {planned.tool_name} {path}"},
        )

    def _build_text_editor_diff(self, planned: PlannedToolCall) -> ArtifactRef:
        from difflib import unified_diff

        path = planned.arguments.get("path")
        command = planned.arguments.get("command")
        if not isinstance(path, str) or not path:
            raise ValueError("project__text_editor: missing path")
        if not isinstance(command, str) or not command:
            raise ValueError("project__text_editor: missing command")

        target = (self._project_root / Path(path)).resolve()
        project_root = self._project_root.resolve()
        if target != project_root and project_root not in target.parents:
            raise PermissionError("project__text_editor: path escapes project root")

        old = ""
        if target.exists() and target.is_file():
            old = target.read_text(encoding="utf-8", errors="replace")

        preview_error: str | None = None
        new = old

        if command == "write":
            file_text = planned.arguments.get("file_text")
            if not isinstance(file_text, str):
                preview_error = "Missing or invalid 'file_text' (expected string)."
            else:
                new = file_text
        elif command == "str_replace":
            old_str = planned.arguments.get("old_str")
            new_str = planned.arguments.get("new_str")
            if not target.exists():
                preview_error = "File not found."
            elif not isinstance(old_str, str) or not old_str:
                preview_error = "Missing or invalid 'old_str' (expected non-empty string)."
            elif not isinstance(new_str, str):
                preview_error = "Missing or invalid 'new_str' (expected string)."
            else:
                count = old.count(old_str)
                if count != 1:
                    preview_error = f"old_str must match exactly once (found {count})."
                else:
                    new = old.replace(old_str, new_str, 1)
        elif command == "insert":
            insert_line_raw = planned.arguments.get("insert_line")
            new_str = planned.arguments.get("new_str")
            if not target.exists():
                preview_error = "File not found."
            elif not isinstance(insert_line_raw, int) or isinstance(insert_line_raw, bool) or insert_line_raw < 1:
                preview_error = "Missing or invalid 'insert_line' (expected int >= 1)."
            elif not isinstance(new_str, str):
                preview_error = "Missing or invalid 'new_str' (expected string)."
            else:
                lines = old.splitlines(keepends=True)
                if insert_line_raw > len(lines) + 1:
                    preview_error = f"insert_line out of range (1..{len(lines) + 1})."
                else:
                    normalized = new_str
                    if not (normalized.endswith("\n") or normalized.endswith("\r\n")):
                        normalized += "\n"
                    idx = insert_line_raw - 1
                    lines[idx:idx] = [normalized]
                    new = "".join(lines)
        else:
            preview_error = f"Unsupported command: {command}"

        if preview_error is not None:
            return self._artifact_store.put(
                f"(preview unavailable)\n{preview_error}",
                kind="diff",
                meta={"summary": f"Preview for {planned.tool_name} {command} {path}"},
            )

        diff_lines = list(
            unified_diff(
                old.splitlines(keepends=True),
                new.splitlines(keepends=True),
                fromfile=f"a/{path}",
                tofile=f"b/{path}",
            )
        )
        diff_text = "".join(diff_lines) or "(no diff)"
        return self._artifact_store.put(
            diff_text,
            kind="diff",
            meta={"summary": f"Diff for {planned.tool_name} {command} {path}"},
        )

    def _build_shell_run_preview(self, planned: PlannedToolCall) -> ArtifactRef:
        command = planned.arguments.get("command")
        cwd = planned.arguments.get("cwd") or "."
        timeout_s = planned.arguments.get("timeout_s")
        if not isinstance(command, str) or not command.strip():
            raise ValueError("shell__run: missing command")
        preview = f"$ {command}\n(cwd: {cwd})\n(timeout_s: {timeout_s})"
        return self._artifact_store.put(
            preview,
            kind="diff",
            meta={"summary": "Shell command preview"},
        )

    def _inspect_strict(self, planned: PlannedToolCall) -> InspectionResult:
        tool_name = planned.tool_name

        # High-risk tools: try to produce a meaningful diff/preview.
        if tool_name == "project__write_text":
            try:
                diff_ref = self._build_write_text_diff(planned)
            except Exception as e:
                code = _classify_tool_exception(e)
                return InspectionResult(
                    decision=InspectionDecision.DENY,
                    action_summary="Invalid write request.",
                    risk_level="high",
                    reason=str(e),
                    error_code=code,
                    diff_ref=None,
                )
            return InspectionResult(
                decision=InspectionDecision.REQUIRE_APPROVAL,
                action_summary=f"Write file: {planned.arguments.get('path')}",
                risk_level="high",
                reason="Strict mode: approve every tool call.",
                error_code=None,
                diff_ref=diff_ref,
            )

        if tool_name == "project__text_editor":
            command = planned.arguments.get("command")
            if command == "view":
                diff_ref = self._build_args_preview(
                    planned,
                    summary=f"Preview for {tool_name} view {planned.arguments.get('path')}",
                )
                return InspectionResult(
                    decision=InspectionDecision.REQUIRE_APPROVAL,
                    action_summary=f"View file: {planned.arguments.get('path')}",
                    risk_level="low",
                    reason="Strict mode: approve every tool call.",
                    error_code=None,
                    diff_ref=diff_ref,
                )
            try:
                diff_ref = self._build_text_editor_diff(planned)
            except Exception as e:
                code = _classify_tool_exception(e)
                return InspectionResult(
                    decision=InspectionDecision.DENY,
                    action_summary="Invalid edit request.",
                    risk_level="high",
                    reason=str(e),
                    error_code=code,
                    diff_ref=None,
                )
            return InspectionResult(
                decision=InspectionDecision.REQUIRE_APPROVAL,
                action_summary=f"Edit file ({command}): {planned.arguments.get('path')}",
                risk_level="high",
                reason="Strict mode: approve every tool call.",
                error_code=None,
                diff_ref=diff_ref,
            )

        if tool_name == "shell__run":
            try:
                diff_ref = self._build_shell_run_preview(planned)
            except Exception as e:
                code = _classify_tool_exception(e)
                return InspectionResult(
                    decision=InspectionDecision.DENY,
                    action_summary="Invalid shell command request.",
                    risk_level="high",
                    reason=str(e),
                    error_code=code,
                    diff_ref=None,
                )
            return InspectionResult(
                decision=InspectionDecision.REQUIRE_APPROVAL,
                action_summary="Run shell command",
                risk_level="high",
                reason="Strict mode: approve every tool call.",
                error_code=None,
                diff_ref=diff_ref,
            )

        # Low-risk tools: require approval but only preview args (do not read file contents).
        diff_ref = self._build_args_preview(planned, summary=f"Preview for {tool_name}")
        return InspectionResult(
            decision=InspectionDecision.REQUIRE_APPROVAL,
            action_summary=f"Execute tool: {tool_name}",
            risk_level="low",
            reason="Strict mode: approve every tool call.",
            error_code=None,
            diff_ref=diff_ref,
        )

    def _build_args_preview(self, planned: PlannedToolCall, *, summary: str) -> ArtifactRef:
        text = json.dumps(planned.arguments, ensure_ascii=False, sort_keys=True, indent=2)
        return self._artifact_store.put(text, kind="diff", meta={"summary": summary})


def _classify_tool_exception(exc: BaseException) -> ErrorCode:
    if isinstance(exc, ToolRuntimeError):
        msg = str(exc).lower()
        if "unknown tool" in msg:
            return ErrorCode.TOOL_UNKNOWN
        return ErrorCode.TOOL_FAILED
    if isinstance(exc, PermissionError):
        return ErrorCode.PERMISSION
    if isinstance(exc, FileNotFoundError):
        return ErrorCode.NOT_FOUND
    if isinstance(exc, TimeoutError):
        return ErrorCode.TIMEOUT
    if isinstance(exc, (ValueError, json.JSONDecodeError)):
        return ErrorCode.BAD_REQUEST
    if isinstance(exc, OSError):
        return ErrorCode.UNKNOWN
    return ErrorCode.UNKNOWN
