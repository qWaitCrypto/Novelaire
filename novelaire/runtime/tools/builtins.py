from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def _require_str(args: dict[str, Any], key: str) -> str:
    value = args.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"Missing or invalid '{key}' (expected non-empty string).")
    return value


def _maybe_int(args: dict[str, Any], key: str) -> int | None:
    value = args.get(key)
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(f"Invalid '{key}' (expected int).")
    if not isinstance(value, int):
        raise ValueError(f"Invalid '{key}' (expected int).")
    return value


def _resolve_in_project(project_root: Path, rel: str) -> Path:
    rel_path = Path(rel)
    if rel_path.is_absolute():
        raise PermissionError("Path must be relative to project root.")
    candidate = (project_root / rel_path).resolve()
    project_root_resolved = project_root.resolve()
    if candidate != project_root_resolved and project_root_resolved not in candidate.parents:
        raise PermissionError("Path escapes project root.")
    return candidate


@dataclass(frozen=True, slots=True)
class ProjectReadTextTool:
    name: str = "project__read_text"
    description: str = (
        "Read a UTF-8 text file under the project root. "
        "Returns at most max_chars characters (default 8000) and always records an artifact reference."
    )
    input_schema: dict[str, Any] = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative path within the project root."},
                "max_chars": {
                    "type": "integer",
                    "description": "Maximum characters to return (default 8000).",
                    "minimum": 1,
                },
            },
            "required": ["path"],
            "additionalProperties": False,
        }
    )

    def execute(self, *, args: dict[str, Any], project_root: Path) -> dict[str, Any]:
        path = _require_str(args, "path")
        max_chars = _maybe_int(args, "max_chars") or 8000
        file_path = _resolve_in_project(project_root, path)
        data = file_path.read_bytes()
        text = data.decode("utf-8", errors="replace")
        truncated = False
        if len(text) > max_chars:
            truncated = True
            text = text[:max_chars]
        return {
            "path": str(Path(path)),
            "truncated": truncated,
            "content": text,
        }


@dataclass(frozen=True, slots=True)
class ProjectWriteTextTool:
    name: str = "project__write_text"
    description: str = (
        "Write UTF-8 text to a file under the project root. "
        "This is a high-risk operation and MUST be approved before execution."
    )
    input_schema: dict[str, Any] = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative path within the project root."},
                "content": {"type": "string", "description": "Full file content to write."},
                "mode": {
                    "type": "string",
                    "enum": ["overwrite", "append"],
                    "description": "Write mode (default overwrite).",
                },
            },
            "required": ["path", "content"],
            "additionalProperties": False,
        }
    )

    def execute(self, *, args: dict[str, Any], project_root: Path) -> dict[str, Any]:
        path = _require_str(args, "path")
        content = _require_str(args, "content")
        mode = args.get("mode") or "overwrite"
        if mode not in ("overwrite", "append"):
            raise ValueError("Invalid 'mode' (expected 'overwrite' or 'append').")

        file_path = _resolve_in_project(project_root, path)
        file_path.parent.mkdir(parents=True, exist_ok=True)

        if mode == "append" and file_path.exists():
            with file_path.open("a", encoding="utf-8") as f:
                f.write(content)
        else:
            file_path.write_text(content, encoding="utf-8")

        return {
            "path": str(Path(path)),
            "mode": mode,
            "bytes_written": len(content.encode("utf-8")),
        }
