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


def _elide_tail(s: str, max_chars: int) -> str:
    if max_chars <= 0:
        return ""
    if len(s) <= max_chars:
        return s
    return s[: max(0, max_chars - 1)].rstrip() + "…"


def _summarize_shell_run_args(args: dict[str, Any], *, max_chars: int = 120) -> str:
    command = args.get("command")
    if not isinstance(command, str) or not command.strip():
        return "Run shell command"
    one_line = " ".join(command.splitlines()).strip()
    one_line = " ".join(one_line.split())
    one_line = _elide_tail(one_line, max_chars)
    return f"Run $ {one_line}"


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

        # Domain invariants / mandatory approvals (override all modes).
        sealed = self._is_spec_sealed()
        sealed_violation = self._check_sealed_spec_violation(planned, sealed=sealed)
        if sealed_violation is not None:
            return sealed_violation

        if planned.tool_name in {"spec__apply", "spec__seal"}:
            return self._inspect_spec_workflow(planned)

        if planned.tool_name == "shell__run" and _shell_run_is_allowlisted(self._project_root, planned.arguments):
            summary = _summarize_shell_run_args(planned.arguments)
            return InspectionResult(
                decision=InspectionDecision.ALLOW,
                action_summary=f"{summary} (allowlisted)",
                risk_level="high",
                reason="Matched local allowlist.",
                error_code=None,
                diff_ref=None,
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
            summary = _summarize_shell_run_args(planned.arguments)
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
                action_summary=summary,
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

    def _is_spec_sealed(self) -> bool:
        import json

        path = self._project_root / ".novelaire" / "state" / "spec_state.json"
        if not path.exists():
            return False
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return False
        if not isinstance(raw, dict):
            return False
        return str(raw.get("status") or "") == "sealed"

    def _check_sealed_spec_violation(self, planned: PlannedToolCall, *, sealed: bool) -> InspectionResult | None:
        if not sealed:
            return None
        tool_name = planned.tool_name
        if tool_name == "project__write_text":
            path = planned.arguments.get("path")
            if isinstance(path, str) and _is_under_spec_dir(path):
                return InspectionResult(
                    decision=InspectionDecision.DENY,
                    action_summary="Blocked write to sealed spec/",
                    risk_level="high",
                    reason="Spec is sealed; do not modify spec/ via generic file tools. Use spec workflow tools.",
                    error_code=ErrorCode.PERMISSION,
                    diff_ref=None,
                )
        if tool_name == "project__text_editor":
            command = planned.arguments.get("command")
            path = planned.arguments.get("path")
            if isinstance(command, str) and command != "view" and isinstance(path, str) and _is_under_spec_dir(path):
                return InspectionResult(
                    decision=InspectionDecision.DENY,
                    action_summary="Blocked edit to sealed spec/",
                    risk_level="high",
                    reason="Spec is sealed; do not modify spec/ via generic file tools. Use spec workflow tools.",
                    error_code=ErrorCode.PERMISSION,
                    diff_ref=None,
                )
        return None

    def _inspect_spec_workflow(self, planned: PlannedToolCall) -> InspectionResult:
        tool_name = planned.tool_name
        if tool_name == "spec__apply":
            proposal_id = planned.arguments.get("proposal_id")
            diff_ref = None
            reason = None
            if isinstance(proposal_id, str) and proposal_id:
                try:
                    record = _load_spec_proposal_record(self._project_root, proposal_id)
                    reason_raw = record.get("reason")
                    if isinstance(reason_raw, str) and reason_raw.strip():
                        reason = reason_raw.strip()
                    raw_ref = record.get("diff_ref")
                    if isinstance(raw_ref, dict):
                        diff_ref = ArtifactRef.from_dict(raw_ref)
                except Exception:
                    diff_ref = self._build_args_preview(planned, summary="Preview for spec__apply (proposal diff unavailable)")
            else:
                diff_ref = self._build_args_preview(planned, summary="Preview for spec__apply (missing proposal_id)")
            return InspectionResult(
                decision=InspectionDecision.REQUIRE_APPROVAL,
                action_summary=f"Apply spec proposal: {proposal_id}",
                risk_level="high",
                reason=reason or "Applying a spec proposal modifies author-visible spec/ files.",
                error_code=None,
                diff_ref=diff_ref,
            )

        if tool_name == "spec__seal":
            label = planned.arguments.get("label")
            preview = (
                "Seal spec into a version label.\n\n"
                "This will create an internal snapshot (git) and mark spec as sealed.\n"
                "Default snapshot exclusions:\n"
                "- .novelaire/state/git\n"
                "- .novelaire/cache\n"
                "- .novelaire/index\n"
                "- .novelaire/tmp\n"
                "- .novelaire/events\n"
                "- .novelaire/sessions\n"
                "- .novelaire/artifacts\n"
            )
            if isinstance(label, str) and label.strip():
                preview = f"Label: {label.strip()}\n\n" + preview
            diff_ref = self._artifact_store.put(preview, kind="diff", meta={"summary": "Spec seal preview"})
            return InspectionResult(
                decision=InspectionDecision.REQUIRE_APPROVAL,
                action_summary=f"Seal spec: {label}",
                risk_level="high",
                reason="Sealing spec creates a version point and makes spec read-only.",
                error_code=None,
                diff_ref=diff_ref,
            )

        return InspectionResult(
            decision=InspectionDecision.DENY,
            action_summary=f"Unknown spec workflow tool: {tool_name}",
            risk_level="high",
            reason="Unsupported spec workflow operation.",
            error_code=ErrorCode.TOOL_UNKNOWN,
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
            summary = _summarize_shell_run_args(planned.arguments)
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
                action_summary=summary,
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


def _is_under_spec_dir(path: str) -> bool:
    normalized = path.replace("\\", "/").lstrip("/")
    return normalized == "spec" or normalized.startswith("spec/")


def _tool_approval_policy_path(project_root: Path) -> Path:
    # Keep this in the author-visible policy dir so users can audit/edit it.
    return project_root / ".novelaire" / "policy" / "tool_approvals.json"


def _load_tool_approval_policy(project_root: Path) -> dict[str, Any]:
    path = _tool_approval_policy_path(project_root)
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return raw if isinstance(raw, dict) else {}


def _save_tool_approval_policy(project_root: Path, policy: dict[str, Any]) -> None:
    path = _tool_approval_policy_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(policy, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
    tmp.replace(path)


def add_shell_run_allowlist_rule(*, project_root: Path, command_prefix: str, cwd: str | None) -> None:
    command_prefix = " ".join(str(command_prefix).splitlines()).strip()
    if not command_prefix:
        return
    policy = _load_tool_approval_policy(project_root)
    rules = policy.get("shell__run_allow", [])
    if not isinstance(rules, list):
        rules = []
    entry: dict[str, Any] = {"command_prefix": command_prefix}
    if cwd is not None and str(cwd).strip():
        entry["cwd"] = str(cwd).strip()
    for existing in rules:
        if not isinstance(existing, dict):
            continue
        if existing.get("command_prefix") == entry.get("command_prefix") and existing.get("cwd") == entry.get("cwd"):
            return
    rules.append(entry)
    policy["shell__run_allow"] = rules
    _save_tool_approval_policy(project_root, policy)


def _normalize_shell_command(command: Any) -> str | None:
    if not isinstance(command, str):
        return None
    one_line = " ".join(command.strip().splitlines()).strip()
    return one_line if one_line else None


def _shell_run_is_allowlisted(project_root: Path, args: dict[str, Any]) -> bool:
    cmd = _normalize_shell_command(args.get("command"))
    if not cmd:
        return False
    cwd = args.get("cwd")
    cwd_s = str(cwd).strip() if isinstance(cwd, str) else None

    policy = _load_tool_approval_policy(project_root)
    rules = policy.get("shell__run_allow", [])
    if not isinstance(rules, list):
        return False
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        prefix = rule.get("command_prefix")
        if not isinstance(prefix, str) or not prefix.strip():
            continue
        if not cmd.startswith(prefix.strip()):
            continue
        rule_cwd = rule.get("cwd")
        if isinstance(rule_cwd, str) and rule_cwd.strip():
            if cwd_s is None or cwd_s != rule_cwd.strip():
                continue
        return True
    return False


def _load_spec_proposal_record(project_root: Path, proposal_id: str) -> dict[str, Any]:
    import json

    root = project_root / ".novelaire" / "state" / "spec" / "proposals"
    path = root / f"{proposal_id}.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("Invalid proposal record.")
    return raw
