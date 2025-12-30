from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import McpConfig, McpServerConfig, load_mcp_config
from .stdio_client import McpToolDef, StdioMcpClient
from ... import __version__


@dataclass(frozen=True, slots=True)
class McpServerStatus:
    name: str
    enabled: bool
    connected: bool
    transport: str
    detail: dict[str, Any]


class McpManager:
    def __init__(self, *, project_root: Path) -> None:
        self._project_root = project_root.expanduser().resolve()
        self._config = load_mcp_config(project_root=self._project_root)
        self._clients: dict[str, StdioMcpClient] = {}

    @property
    def config(self) -> McpConfig:
        return self._config

    def reload_config(self) -> None:
        self._config = load_mcp_config(project_root=self._project_root)
        for name in list(self._clients):
            cfg = self._config.servers.get(name)
            if cfg is None or not cfg.enabled:
                try:
                    self._clients[name].close()
                except Exception:
                    pass
                self._clients.pop(name, None)

    def close_all(self) -> None:
        for client in list(self._clients.values()):
            try:
                client.close()
            except Exception:
                pass
        self._clients.clear()

    def list_servers(self) -> list[McpServerStatus]:
        out: list[McpServerStatus] = []
        for name, cfg in sorted(self._config.servers.items()):
            client = self._clients.get(name)
            connected = client.is_running() if client is not None else False
            out.append(
                McpServerStatus(
                    name=name,
                    enabled=cfg.enabled,
                    connected=connected,
                    transport="stdio",
                    detail={
                        "command": cfg.command,
                        "args": list(cfg.args),
                        "cwd": cfg.cwd,
                        "timeout_s": cfg.timeout_s,
                        "source": self._config.source,
                    },
                )
            )
        return out

    def list_tools(self, *, server: str, timeout_s: float | None = None) -> list[McpToolDef]:
        client = self._get_client(server)
        return client.list_tools(timeout_s=timeout_s)

    def call_tool(
        self,
        *,
        server: str,
        tool: str,
        arguments: dict[str, Any] | None,
        timeout_s: float | None,
    ) -> dict[str, Any]:
        client = self._get_client(server)
        return client.call_tool(name=tool, arguments=arguments, timeout_s=timeout_s)

    def _get_client(self, server: str) -> StdioMcpClient:
        if not isinstance(server, str) or not server.strip():
            raise ValueError("Missing or invalid 'server' (expected non-empty string).")
        server = server.strip()
        cfg = self._config.servers.get(server)
        if cfg is None:
            raise ValueError(f"Unknown MCP server: {server}")
        if not cfg.enabled:
            raise PermissionError(f"MCP server is disabled: {server} (enable it in .novelaire/config/mcp.json)")

        existing = self._clients.get(server)
        if existing is not None:
            try:
                existing.ensure_connected()
                return existing
            except Exception:
                try:
                    existing.close()
                except Exception:
                    pass
                self._clients.pop(server, None)

        if not cfg.command:
            raise ValueError(f"MCP server '{server}' is missing command.")

        client = StdioMcpClient(
            command=cfg.command,
            args=list(cfg.args),
            env=dict(cfg.env),
            cwd=cfg.cwd,
            timeout_s=cfg.timeout_s,
            client_name="novelaire",
            client_version=__version__,
        )
        client.ensure_connected()
        self._clients[server] = client
        return client
