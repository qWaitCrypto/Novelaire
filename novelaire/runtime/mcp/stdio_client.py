from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Any


class McpError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class McpToolDef:
    name: str
    description: str | None
    input_schema: dict[str, Any] | None


def _now() -> float:
    return time.monotonic()


class StdioMcpClient:
    """
    Minimal MCP client over stdio (JSON-RPC 2.0, line-delimited).

    Supports:
    - initialize / initialized
    - tools/list
    - tools/call
    """

    def __init__(
        self,
        *,
        command: str,
        args: list[str],
        env: dict[str, str] | None,
        cwd: str | None,
        timeout_s: float,
        client_name: str = "novelaire",
        client_version: str = "0.0",
    ) -> None:
        self._command = command
        self._args = list(args)
        self._env = dict(env or {})
        self._cwd = cwd
        self._timeout_s = float(timeout_s) if timeout_s else 60.0
        self._client_name = client_name
        self._client_version = client_version

        self._proc: subprocess.Popen[str] | None = None
        self._reader: threading.Thread | None = None

        self._lock = threading.RLock()
        self._next_id = 1
        self._pending: dict[int, dict[str, Any]] = {}
        self._pending_err: dict[int, BaseException] = {}
        self._cv = threading.Condition(self._lock)

        self._server_info: dict[str, Any] | None = None

    def is_running(self) -> bool:
        with self._lock:
            return self._proc is not None and self._proc.poll() is None

    def close(self) -> None:
        with self._lock:
            proc = self._proc
            self._proc = None
            self._server_info = None
            self._pending.clear()
            self._pending_err.clear()
            self._cv.notify_all()
        if proc is not None:
            try:
                if proc.stdin is not None:
                    proc.stdin.close()
            except Exception:
                pass
            try:
                if proc.stdout is not None:
                    proc.stdout.close()
            except Exception:
                pass
            try:
                proc.terminate()
            except Exception:
                pass
            try:
                proc.wait(timeout=0.5)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass

    def ensure_connected(self) -> None:
        if self.is_running() and self._server_info is not None:
            return
        self._start()
        self._initialize()

    def list_tools(self, *, timeout_s: float | None = None) -> list[McpToolDef]:
        self.ensure_connected()
        result = self._request("tools/list", params={}, timeout_s=timeout_s)
        tools = result.get("tools")
        if not isinstance(tools, list):
            raise McpError("Invalid tools/list response: missing tools list.")
        out: list[McpToolDef] = []
        for item in tools:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            if not isinstance(name, str) or not name:
                continue
            desc = item.get("description") if isinstance(item.get("description"), str) else None
            schema = item.get("inputSchema") if isinstance(item.get("inputSchema"), dict) else None
            out.append(McpToolDef(name=name, description=desc, input_schema=schema))
        return out

    def call_tool(
        self,
        *,
        name: str,
        arguments: dict[str, Any] | None,
        timeout_s: float | None = None,
    ) -> dict[str, Any]:
        self.ensure_connected()
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Missing or invalid tool name.")
        params: dict[str, Any] = {"name": name}
        if arguments is not None:
            params["arguments"] = dict(arguments)
        result = self._request("tools/call", params=params, timeout_s=timeout_s)
        if not isinstance(result, dict):
            raise McpError("Invalid tools/call response.")
        return result

    def server_info(self) -> dict[str, Any] | None:
        return dict(self._server_info) if isinstance(self._server_info, dict) else None

    def _start(self) -> None:
        with self._lock:
            if self._proc is not None and self._proc.poll() is None:
                return
            if not self._command:
                raise ValueError("MCP server command is empty.")
            proc = subprocess.Popen(
                [self._command, *self._args],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                cwd=self._cwd or None,
                env={**dict(os.environ), **self._env},
            )
            self._proc = proc
            self._reader = threading.Thread(target=self._read_loop, name="mcp-stdio-reader", daemon=True)
            self._reader.start()

    def _read_loop(self) -> None:
        while True:
            with self._lock:
                proc = self._proc
            if proc is None:
                return
            if proc.stdout is None:
                return
            line = proc.stdout.readline()
            if line == "":
                return
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except Exception:
                continue
            if not isinstance(msg, dict):
                continue
            msg_id = msg.get("id")
            if isinstance(msg_id, int):
                with self._lock:
                    if "error" in msg:
                        self._pending_err[msg_id] = McpError(str(msg.get("error")))
                    else:
                        self._pending[msg_id] = msg
                    self._cv.notify_all()
            else:
                # Notification; ignore in v0.3.
                continue

    def _initialize(self) -> None:
        init_params = {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": self._client_name, "version": self._client_version},
        }
        result = self._request("initialize", params=init_params, timeout_s=self._timeout_s)
        if not isinstance(result, dict):
            raise McpError("Invalid initialize result.")
        with self._lock:
            self._server_info = result
        # Send initialized notification (best-effort).
        try:
            self._notify("initialized", params={})
        except Exception:
            pass

    def _notify(self, method: str, *, params: dict[str, Any] | None) -> None:
        with self._lock:
            proc = self._proc
        if proc is None or proc.stdin is None or proc.poll() is not None:
            raise McpError("MCP server is not running.")
        msg = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        proc.stdin.write(json.dumps(msg, ensure_ascii=False) + "\n")
        proc.stdin.flush()

    def _request(self, method: str, *, params: dict[str, Any] | None, timeout_s: float | None) -> dict[str, Any]:
        with self._lock:
            proc = self._proc
        if proc is None or proc.stdin is None or proc.poll() is not None:
            raise McpError("MCP server is not running.")

        with self._lock:
            msg_id = self._next_id
            self._next_id += 1

        msg = {"jsonrpc": "2.0", "id": msg_id, "method": method}
        if params is not None:
            msg["params"] = params

        try:
            proc.stdin.write(json.dumps(msg, ensure_ascii=False) + "\n")
            proc.stdin.flush()
        except Exception as e:
            raise McpError(f"Failed to write to MCP server stdin: {e}") from e

        deadline = _now() + (float(timeout_s) if timeout_s is not None else self._timeout_s)
        with self._lock:
            while True:
                if msg_id in self._pending_err:
                    err = self._pending_err.pop(msg_id)
                    raise err
                if msg_id in self._pending:
                    resp = self._pending.pop(msg_id)
                    break
                if proc.poll() is not None:
                    raise McpError("MCP server exited.")
                remaining = deadline - _now()
                if remaining <= 0:
                    raise TimeoutError(f"MCP request timed out: {method}")
                self._cv.wait(timeout=min(0.25, remaining))

        if not isinstance(resp, dict):
            raise McpError("Invalid MCP response.")
        if "result" not in resp:
            raise McpError(f"MCP response missing result for {method}.")
        result = resp.get("result")
        return result if isinstance(result, dict) else {"result": result}
