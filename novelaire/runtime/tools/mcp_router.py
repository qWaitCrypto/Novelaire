from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .builtins import _maybe_bool, _maybe_int, _maybe_float, _require_str
from ..mcp.manager import McpManager


def _join_text_content(content: Any) -> str:
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "text" and isinstance(item.get("text"), str):
            parts.append(item["text"])
    return "\n".join([p for p in parts if p.strip()])


def _truncate_text(s: str, *, max_chars: int) -> tuple[str, bool]:
    if max_chars < 1:
        return "", True
    if len(s) <= max_chars:
        return s, False
    return s[:max_chars], True


def _truncate_content(content: Any, *, max_chars: int, max_items: int) -> tuple[Any, bool]:
    if not isinstance(content, list):
        return content, False
    truncated = False
    out: list[Any] = []
    for item in content[:max_items]:
        if not isinstance(item, dict):
            out.append(item)
            continue
        if item.get("type") == "text" and isinstance(item.get("text"), str):
            txt, t = _truncate_text(item["text"], max_chars=max_chars)
            if t:
                truncated = True
            out.append({**item, "text": txt})
        else:
            out.append(item)
    if len(content) > max_items:
        truncated = True
    return out, truncated


@dataclass(frozen=True, slots=True)
class McpListServersTool:
    manager: McpManager
    name: str = "mcp__list_servers"
    description: str = "List configured MCP servers for this project (router mode)."
    input_schema: dict[str, Any] = field(
        default_factory=lambda: {"type": "object", "properties": {}, "additionalProperties": False}
    )

    def execute(self, *, args: dict[str, Any], project_root) -> dict[str, Any]:
        del args, project_root
        self.manager.reload_config()
        servers = self.manager.list_servers()
        return {
            "ok": True,
            "servers": [
                {
                    "name": s.name,
                    "enabled": s.enabled,
                    "connected": s.connected,
                    "transport": s.transport,
                    "detail": s.detail,
                }
                for s in servers
            ],
        }


@dataclass(frozen=True, slots=True)
class McpListToolsTool:
    manager: McpManager
    name: str = "mcp__list_tools"
    description: str = "List tools advertised by an MCP server (router mode)."
    input_schema: dict[str, Any] = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "server": {"type": "string", "description": "MCP server name from mcp__list_servers."},
                "tool_name": {"type": "string", "description": "Optional single tool name to include schema for."},
                "include_schemas": {
                    "type": "boolean",
                    "description": "Include input_schema for all tools (default false).",
                },
                "max_tools": {"type": "integer", "minimum": 1, "description": "Maximum tools to return (default 100)."},
                "timeout_s": {"type": "number", "minimum": 0, "description": "Optional request timeout override."},
            },
            "required": ["server"],
            "additionalProperties": False,
        }
    )

    def execute(self, *, args: dict[str, Any], project_root) -> dict[str, Any]:
        del project_root
        self.manager.reload_config()
        server = _require_str(args, "server").strip()
        tool_name = args.get("tool_name")
        if tool_name is not None and not isinstance(tool_name, str):
            raise ValueError("Invalid 'tool_name' (expected string).")
        tool_name = tool_name.strip() if isinstance(tool_name, str) and tool_name.strip() else None
        include_schemas = _maybe_bool(args, "include_schemas") or False
        max_tools = _maybe_int(args, "max_tools") or 100
        timeout_s = _maybe_float(args, "timeout_s")

        tools = self.manager.list_tools(server=server, timeout_s=timeout_s)
        if tool_name is not None:
            tools = [t for t in tools if t.name == tool_name]
        if len(tools) > max_tools:
            tools = tools[:max_tools]
            truncated = True
        else:
            truncated = False

        return {
            "ok": True,
            "server": server,
            "truncated": truncated,
            "tools": [
                {
                    "name": t.name,
                    "description": t.description,
                    "input_schema": t.input_schema if include_schemas or (tool_name is not None) else None,
                }
                for t in tools
            ],
        }


@dataclass(frozen=True, slots=True)
class McpCallToolTool:
    manager: McpManager
    name: str = "mcp__call_tool"
    description: str = "Call an MCP tool via router mode (server + tool name + JSON args)."
    input_schema: dict[str, Any] = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "server": {"type": "string"},
                "tool": {"type": "string"},
                "arguments": {"type": "object", "description": "JSON object passed as MCP tool arguments."},
                "timeout_s": {"type": "number", "minimum": 0, "description": "Optional request timeout override."},
                "max_chars": {"type": "integer", "minimum": 1, "description": "Max chars for returned text preview."},
            },
            "required": ["server", "tool", "arguments"],
            "additionalProperties": False,
        }
    )

    def execute(self, *, args: dict[str, Any], project_root) -> dict[str, Any]:
        del project_root
        self.manager.reload_config()
        server = _require_str(args, "server").strip()
        tool = _require_str(args, "tool").strip()
        arguments = args.get("arguments")
        if not isinstance(arguments, dict):
            raise ValueError("Invalid 'arguments' (expected object).")
        timeout_s = _maybe_float(args, "timeout_s")
        max_chars = _maybe_int(args, "max_chars") or 8000

        result = self.manager.call_tool(server=server, tool=tool, arguments=arguments, timeout_s=timeout_s)
        raw_content = result.get("content")
        content, content_truncated = _truncate_content(raw_content, max_chars=max_chars, max_items=40)
        text, text_truncated = _truncate_text(_join_text_content(content), max_chars=max_chars)
        truncated = content_truncated or text_truncated

        return {
            "ok": True,
            "server": server,
            "tool": tool,
            "is_error": bool(result.get("isError")) if isinstance(result, dict) else False,
            "content": content,
            "text": text,
            "truncated": truncated,
        }
