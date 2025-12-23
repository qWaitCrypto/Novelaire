from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from . import __version__
from .runtime.event_bus import EventBus, EventFilter, EventLogAppendError
from .runtime.ids import new_id, now_ts_ms
from .runtime.orchestrator import Orchestrator
from .runtime.project import RuntimePaths
from .runtime.approval import ApprovalStatus
from .runtime.protocol import ArtifactRef, EventKind, Op, OpKind
from .runtime.stores import FileApprovalStore, FileArtifactStore, FileEventLogStore, FileSessionStore
from .runtime.llm.config_io import load_model_config_layers_for_dir
from .runtime.validate import validate_bundle_dir, validate_project_session

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_DENIED = 2
EXIT_VALIDATION_FAILED = 3
EXIT_TOOL_FAILED = 4
EXIT_CONFIG_ERROR = 5


def _configure_text_io() -> None:
    """
    Best-effort I/O normalization for interactive terminals.

    On WSL/Linux it's common to have sys.stdin.errors='surrogateescape'. If invalid byte
    sequences are read from the terminal/clipboard, Python preserves them as surrogate
    codepoints in the resulting str, which later crashes when encoding to UTF-8 for persistence.
    """

    try:
        if hasattr(sys.stdin, "reconfigure"):
            sys.stdin.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")
    except Exception:
        return


def _sanitize_text(text: str) -> str:
    # Replace illegal Unicode surrogate codepoints (U+D800..U+DFFF) with U+FFFD.
    out: list[str] = []
    changed = False
    for ch in text:
        o = ord(ch)
        if 0xD800 <= o <= 0xDFFF:
            out.append("\uFFFD")
            changed = True
        else:
            out.append(ch)
    return "".join(out) if changed else text


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="novelaire",
        description="Spec-driven vibe writing CLI.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Initialize a novel project directory.")
    init_parser.add_argument(
        "path",
        nargs="?",
        default=".",
        help="Target directory (default: current directory).",
    )
    init_parser.set_defaults(func=_cmd_init)

    chat_parser = subparsers.add_parser("chat", help="Start an interactive writing session.")
    chat_parser.add_argument(
        "--session",
        dest="session_id",
        default=None,
        help="Resume an existing session by ID.",
    )
    chat_parser.add_argument(
        "--timeout",
        dest="timeout_s",
        type=float,
        default=None,
        help="Per-request timeout in seconds (no default).",
    )
    chat_parser.add_argument(
        "--system",
        dest="system_prompt",
        default=None,
        help="Optional system prompt override.",
    )
    chat_parser.add_argument(
        "--tools",
        dest="enable_tools",
        action="store_true",
        help="Enable tool calling (requires model profile supports_tools=true).",
    )
    chat_parser.set_defaults(func=_cmd_chat)

    session_parser = subparsers.add_parser("session", help="Manage sessions.")
    session_subparsers = session_parser.add_subparsers(dest="session_cmd", required=True)
    session_list_parser = session_subparsers.add_parser("list", help="List sessions.")
    session_list_parser.set_defaults(func=_cmd_session_list)
    session_resume_parser = session_subparsers.add_parser("resume", help="Resume a session.")
    session_resume_parser.add_argument("session_id", help="Session ID to resume.")
    session_resume_parser.add_argument(
        "--timeout",
        dest="timeout_s",
        type=float,
        default=None,
        help="Per-request timeout in seconds (no default).",
    )
    session_resume_parser.add_argument(
        "--system",
        dest="system_prompt",
        default=None,
        help="Optional system prompt override.",
    )
    session_resume_parser.add_argument(
        "--tools",
        dest="enable_tools",
        action="store_true",
        help="Enable tool calling (requires model profile supports_tools=true).",
    )
    session_resume_parser.set_defaults(func=_cmd_session_resume)

    debug_parser = subparsers.add_parser("debug", help="Debug utilities.")
    debug_subparsers = debug_parser.add_subparsers(dest="debug_cmd", required=True)
    debug_export_parser = debug_subparsers.add_parser("export", help="Export a replay bundle.")
    debug_export_parser.add_argument("session_id", help="Session ID to export.")
    debug_export_parser.add_argument(
        "-o",
        "--output",
        default=".",
        help="Output directory (default: current directory).",
    )
    debug_export_parser.set_defaults(func=_cmd_debug_export)

    debug_validate_parser = debug_subparsers.add_parser("validate", help="Validate a session log or bundle.")
    debug_validate_parser.add_argument(
        "target",
        help="Session ID (in current project) or bundle directory path.",
    )
    debug_validate_parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat unknown kinds/missing store references as errors.",
    )
    debug_validate_parser.set_defaults(func=_cmd_debug_validate)

    return parser


def _cmd_not_implemented(_: argparse.Namespace) -> int:
    print("Not implemented yet.", file=sys.stderr)
    return EXIT_ERROR


def _cmd_chat(args: argparse.Namespace) -> int:
    try:
        paths = RuntimePaths.discover()
    except FileNotFoundError as e:
        print(str(e), file=sys.stderr)
        return EXIT_CONFIG_ERROR

    artifact_store = FileArtifactStore(paths.artifacts_dir)
    session_store = FileSessionStore(paths.sessions_dir)
    approval_store = FileApprovalStore(paths.state_dir / "approvals")
    event_log_store = FileEventLogStore(
        paths.events_dir, artifact_store=artifact_store, session_store=session_store
    )
    event_bus = EventBus(event_log_store=event_log_store)

    try:
        layers = load_model_config_layers_for_dir(paths.project_root, require_project=True)
        model_config = layers.merged()
    except Exception as e:
        print(str(e), file=sys.stderr)
        return EXIT_CONFIG_ERROR

    session_id = args.session_id
    if session_id is None:
        session_id = session_store.create_session(
            {
                "project_ref": str(paths.project_root),
                "mode": "chat",
            }
        )
    else:
        try:
            session_store.get_session(session_id)
        except FileNotFoundError as e:
            print(str(e), file=sys.stderr)
            return EXIT_CONFIG_ERROR

    orchestrator = Orchestrator.for_session(
        project_root=paths.project_root,
        session_id=session_id,
        event_bus=event_bus,
        session_store=session_store,
        event_log_store=event_log_store,
        artifact_store=artifact_store,
        approval_store=approval_store,
        model_config=model_config,
        system_prompt=args.system_prompt,
        tools_enabled=bool(getattr(args, "enable_tools", False)),
    )
    orchestrator.load_history_from_events()

    return _run_chat_line_mode(
        orchestrator=orchestrator,
        event_bus=event_bus,
        session_id=session_id,
        approval_store=approval_store,
        event_log_store=event_log_store,
        artifact_store=artifact_store,
        timeout_s=args.timeout_s,
        print_replay=bool(args.session_id is not None),
    )


def _run_chat_line_mode(
    *,
    orchestrator: Orchestrator,
    event_bus: EventBus,
    session_id: str,
    approval_store: FileApprovalStore,
    event_log_store: FileEventLogStore,
    artifact_store: FileArtifactStore,
    timeout_s: float | None,
    print_replay: bool,
) -> int:
    return _run_chat_console_ui(
        orchestrator=orchestrator,
        event_bus=event_bus,
        session_id=session_id,
        approval_store=approval_store,
        event_log_store=event_log_store,
        artifact_store=artifact_store,
        timeout_s=timeout_s,
        print_replay=print_replay,
    )


def _run_chat_console_ui(
    *,
    orchestrator: Orchestrator,
    event_bus: EventBus,
    session_id: str,
    approval_store: FileApprovalStore,
    event_log_store: FileEventLogStore,
    artifact_store: FileArtifactStore,
    timeout_s: float | None,
    print_replay: bool,
) -> int:
    import threading
    from pathlib import Path
    from contextlib import contextmanager

    from .runtime.llm.errors import CancellationToken
    from .ui.console_ui import ConsoleUI, ThinkTagParser, UIEvent, UIEventKind

    def _is_tty() -> bool:
        try:
            return bool(sys.stdin.isatty() and sys.stdout.isatty())
        except Exception:
            return False

    # Input: prompt_toolkit if available in a TTY; otherwise basic input().
    prompt_session = None
    if _is_tty():
        try:
            from prompt_toolkit import PromptSession
            from prompt_toolkit.completion import Completer, Completion
            from prompt_toolkit.history import FileHistory
            from prompt_toolkit.key_binding import KeyBindings
            from prompt_toolkit.keys import Keys

            class _SlashCompleter(Completer):
                _cmds = ["/help", "/clear", "/exit", "/quit"]

                def get_completions(self, document, complete_event):
                    text = document.text_before_cursor
                    if not text.startswith("/"):
                        return
                    for c in self._cmds:
                        if c.startswith(text):
                            yield Completion(c, start_position=-len(text))

            kb = KeyBindings()

            @kb.add(Keys.ControlJ)
            def _(event) -> None:
                event.current_buffer.insert_text("\n")

            @kb.add(Keys.Enter)
            def _(event) -> None:
                event.current_buffer.validate_and_handle()

            history_path = Path(approval_store._root).parent / "history.txt"  # state/history.txt
            try:
                history_path.parent.mkdir(parents=True, exist_ok=True)
            except Exception:
                pass
            prompt_session = PromptSession(
                message="You> ",
                multiline=True,
                key_bindings=kb,
                completer=_SlashCompleter(),
                history=FileHistory(str(history_path)),
            )
        except Exception:
            prompt_session = None

    ui = ConsoleUI(stream=sys.stdout, enable_color=_is_tty())
    ui.start()
    ui.print_header(session_id=session_id)

    # Replay (resume) through UI to keep a single output channel.
    if print_replay:
        _emit_replay_to_ui(
            session_id,
            ui=ui,
            event_log_store=event_log_store,
            artifact_store=artifact_store,
        )

    think_parser = ThinkTagParser()

    def _on_runtime_event(event) -> None:
        for uiev in _runtime_event_to_ui_events(event, think_parser=think_parser):
            ui.emit(uiev)

    event_bus.subscribe(_on_runtime_event, EventFilter(session_id=session_id))

    @contextmanager
    def _quiet_stdin_while_waiting():
        # Prevent "type-ahead" from being echoed into the spinner line while we are waiting
        # (the main thread is not reading input during LLM streaming).
        try:
            if not sys.stdin.isatty():
                yield
                return
        except Exception:
            yield
            return
        try:
            import termios  # type: ignore

            fd = sys.stdin.fileno()
            old = termios.tcgetattr(fd)
            new = list(old)
            new[3] = new[3] & ~termios.ECHO
            termios.tcsetattr(fd, termios.TCSADRAIN, new)
            try:
                yield
            finally:
                try:
                    termios.tcsetattr(fd, termios.TCSADRAIN, old)
                    termios.tcflush(fd, termios.TCIFLUSH)
                except Exception:
                    pass
        except Exception:
            yield

    def _wait_with_ctrl_c(thread: threading.Thread, cancel: CancellationToken) -> None:
        cancelled_once = False
        with _quiet_stdin_while_waiting():
            while thread.is_alive():
                try:
                    thread.join(timeout=0.1)
                except KeyboardInterrupt:
                    if not cancelled_once:
                        cancelled_once = True
                        cancel.cancel()
                        ui.emit(
                            UIEvent(
                                UIEventKind.CANCELLED,
                                {"message": "cancelling… (press Ctrl+C again to force exit)"},
                            )
                        )
                    else:
                        raise

    def _prompt(text: str = "You> ") -> str:
        if prompt_session is not None:
            return prompt_session.prompt(text)
        return input(text)

    def _handle_pending_approvals_ui(*, request_id: str | None) -> None:
        while True:
            pending = approval_store.list(session_id=session_id, status=ApprovalStatus.PENDING, request_id=request_id)
            if not pending:
                return
            record = pending[0]
            ui.emit(
                UIEvent(
                    UIEventKind.WARNING,
                    {"message": f"Approval required: {record.approval_id}\n{record.action_summary}"},
                )
            )
            while True:
                try:
                    ans = _prompt("Decision [a=approve/d=deny] > ").strip().lower()
                except KeyboardInterrupt:
                    ui.emit(UIEvent(UIEventKind.WARNING, {"message": "Approval decision cancelled; still pending."}))
                    break
                decision = (
                    "approve"
                    if ans in {"a", "approve", "yes", "y"}
                    else "deny"
                    if ans in {"d", "deny", "no", "n"}
                    else ""
                )
                if not decision:
                    ui.emit(UIEvent(UIEventKind.WARNING, {"message": "Please type 'a' or 'd'."}))
                    continue
                op = Op(
                    kind=OpKind.APPROVAL_DECISION.value,
                    payload={"approval_id": record.approval_id, "decision": decision},
                    session_id=session_id,
                    request_id=new_id("req"),
                    timestamp=now_ts_ms(),
                    turn_id=new_id("turn"),
                )
                cancel = CancellationToken()
                t = threading.Thread(
                    target=lambda: orchestrator.handle(op, timeout_s=timeout_s, cancel=cancel),
                    daemon=True,
                )
                t.start()
                _wait_with_ctrl_c(t, cancel)
                break

    # Initial approvals (resume case).
    try:
        _handle_pending_approvals_ui(request_id=None)
    except EventLogAppendError as e:
        ui.emit(UIEvent(UIEventKind.ERROR_RAISED, {"code": "event_log", "message": str(e), "recoverable": False}))
        ui.stop()
        return EXIT_CONFIG_ERROR

    while True:
        try:
            user_text = _prompt("You> ")
        except (EOFError, KeyboardInterrupt):
            break

        user_text = _sanitize_text(user_text).strip("\n")
        if not user_text.strip():
            continue

        cmd = user_text.strip()
        if cmd in {"/exit", "/quit"}:
            break
        if cmd in {"/help", "/?"}:
            ui.emit(
                UIEvent(
                    UIEventKind.LOG,
                    {"level": "help", "message": "Enter=send; Ctrl+J=newline; Ctrl+C=cancel; /clear clears; /exit quits."},
                )
            )
            continue
        if cmd == "/clear":
            ui.emit(UIEvent(UIEventKind.CLEAR_SCREEN, {}))
            continue

        try:
            _handle_pending_approvals_ui(request_id=None)
        except EventLogAppendError as e:
            ui.emit(UIEvent(UIEventKind.ERROR_RAISED, {"code": "event_log", "message": str(e), "recoverable": False}))
            break

        op = Op(
            kind=OpKind.CHAT.value,
            payload={"text": cmd},
            session_id=session_id,
            request_id=new_id("req"),
            timestamp=now_ts_ms(),
            turn_id=new_id("turn"),
        )
        cancel = CancellationToken()
        t = threading.Thread(target=lambda: orchestrator.handle(op, timeout_s=timeout_s, cancel=cancel), daemon=True)
        t.start()
        try:
            _wait_with_ctrl_c(t, cancel)
        except KeyboardInterrupt:
            break

        try:
            _handle_pending_approvals_ui(request_id=op.request_id)
        except (KeyboardInterrupt, EventLogAppendError):
            break

    try:
        event_bus.flush()
    except EventLogAppendError as e:
        ui.emit(UIEvent(UIEventKind.ERROR_RAISED, {"code": "event_log", "message": str(e), "recoverable": False}))
        ui.stop()
        return EXIT_CONFIG_ERROR

    ui.stop()
    return EXIT_OK


def _run_chat_basic_line_mode(
    *,
    orchestrator: Orchestrator,
    event_bus: EventBus,
    session_id: str,
    approval_store: FileApprovalStore,
    event_log_store: FileEventLogStore,
    artifact_store: FileArtifactStore,
    timeout_s: float | None,
    print_replay: bool,
) -> int:
    if print_replay:
        _print_replay(session_id, event_log_store=event_log_store, artifact_store=artifact_store)

    try:
        _handle_pending_approvals(
            orchestrator=orchestrator,
            session_id=session_id,
            approval_store=approval_store,
            timeout_s=timeout_s,
        )
    except EventLogAppendError as e:
        print(f"[fatal] {e}", file=sys.stderr)
        return EXIT_CONFIG_ERROR

    assistant_last_char_newline = True

    def _ui_handler(event) -> None:
        nonlocal assistant_last_char_newline
        if event.kind == EventKind.LLM_RESPONSE_DELTA.value:
            delta = str(event.payload.get("text_delta") or "")
            sys.stdout.write(delta)
            sys.stdout.flush()
            assistant_last_char_newline = delta.endswith("\n")
        elif event.kind == EventKind.LLM_RESPONSE_COMPLETED.value:
            if not assistant_last_char_newline:
                sys.stdout.write("\n")
                sys.stdout.flush()
            assistant_last_char_newline = True
        elif event.kind == EventKind.OPERATION_PROGRESS.value:
            msg = event.payload.get("message") if isinstance(event.payload, dict) else None
            if msg:
                print(f"[progress] {msg}", file=sys.stderr)
        elif event.kind == EventKind.OPERATION_CANCELLED.value:
            sys.stdout.write("\n")
            sys.stdout.flush()
            reason = event.payload.get("reason") or "cancelled"
            print(f"[cancelled] {reason}", file=sys.stderr)
        elif event.kind in (EventKind.OPERATION_FAILED.value, EventKind.LLM_REQUEST_FAILED.value):
            msg = event.payload.get("error") or event.payload
            print(f"[error] {msg}", file=sys.stderr)

    event_bus.subscribe(_ui_handler, EventFilter(session_id=session_id))

    print(f"Session: {session_id}")
    print("Type '/exit' to quit.")
    while True:
        try:
            user_text = input("> ")
        except EOFError:
            print()
            break
        except KeyboardInterrupt:
            print()
            continue
        if user_text.strip() in {"/exit", "/quit"}:
            break
        user_text = _sanitize_text(user_text)
        op = Op(
            kind=OpKind.CHAT.value,
            payload={"text": user_text},
            session_id=session_id,
            request_id=new_id("req"),
            timestamp=now_ts_ms(),
            turn_id=new_id("turn"),
        )
        try:
            orchestrator.handle(op, timeout_s=timeout_s)
            _handle_pending_approvals(
                orchestrator=orchestrator,
                session_id=session_id,
                approval_store=approval_store,
                request_id=op.request_id,
                timeout_s=timeout_s,
            )
        except EventLogAppendError as e:
            print(f"[fatal] {e}", file=sys.stderr)
            return EXIT_CONFIG_ERROR
        except KeyboardInterrupt:
            print("\nCancelled.", file=sys.stderr)
            continue

    try:
        event_bus.flush()
    except EventLogAppendError as e:
        print(f"[fatal] {e}", file=sys.stderr)
        return EXIT_CONFIG_ERROR

    return EXIT_OK


def _cmd_session_list(_: argparse.Namespace) -> int:
    try:
        paths = RuntimePaths.discover()
    except FileNotFoundError as e:
        print(str(e), file=sys.stderr)
        return EXIT_CONFIG_ERROR

    session_store = FileSessionStore(paths.sessions_dir)
    sessions = session_store.list_sessions()
    for meta in sessions:
        sid = meta.get("session_id")
        updated = meta.get("updated_at")
        mode = meta.get("mode")
        print(f"{sid}\tupdated_at={updated}\tmode={mode}")
    return EXIT_OK


def _cmd_session_resume(args: argparse.Namespace) -> int:
    args2 = argparse.Namespace(
        session_id=args.session_id,
        timeout_s=args.timeout_s,
        system_prompt=args.system_prompt,
        enable_tools=getattr(args, "enable_tools", False),
    )
    return _cmd_chat(args2)


def _cmd_debug_export(args: argparse.Namespace) -> int:
    try:
        paths = RuntimePaths.discover()
    except FileNotFoundError as e:
        print(str(e), file=sys.stderr)
        return EXIT_CONFIG_ERROR

    artifact_store = FileArtifactStore(paths.artifacts_dir)
    session_store = FileSessionStore(paths.sessions_dir)
    approval_store = FileApprovalStore(paths.state_dir / "approvals")
    event_log_store = FileEventLogStore(
        paths.events_dir, artifact_store=artifact_store, session_store=session_store
    )

    output_dir = Path(args.output).expanduser().resolve()
    try:
        bundle_dir = event_log_store.export_bundle(args.session_id, output_dir)
    except FileNotFoundError as e:
        print(str(e), file=sys.stderr)
        return EXIT_CONFIG_ERROR

    try:
        _export_extra_runtime_dirs(
            bundle_dir=bundle_dir,
            config_dir=paths.config_dir,
            policy_dir=paths.policy_dir,
            state_dir=paths.state_dir,
        )
        _export_approval_artifacts(
            session_id=args.session_id,
            approval_store=approval_store,
            artifact_store=artifact_store,
            bundle_artifacts_dir=bundle_dir / "artifacts",
        )
    except Exception as e:
        print(f"Export failed: {e}", file=sys.stderr)
        return EXIT_ERROR

    print(str(bundle_dir))
    return EXIT_OK


def _cmd_debug_validate(args: argparse.Namespace) -> int:
    strict = bool(getattr(args, "strict", False))
    target = str(args.target)
    target_path = Path(target).expanduser()
    if target_path.exists():
        issues = validate_bundle_dir(bundle_dir=target_path, strict=strict)
    else:
        try:
            paths = RuntimePaths.discover()
        except FileNotFoundError as e:
            print(str(e), file=sys.stderr)
            return EXIT_CONFIG_ERROR
        issues = validate_project_session(project_root=paths.project_root, session_id=target, strict=strict)

    errors = [i for i in issues if i.severity == "error"]
    for issue in issues:
        stream = sys.stderr if issue.severity == "error" else sys.stdout
        print(issue.render(), file=stream)

    if errors:
        print(f"Validation failed: {len(errors)} error(s), {len(issues) - len(errors)} warning(s).", file=sys.stderr)
        return EXIT_VALIDATION_FAILED
    if issues:
        print(f"Validation passed with {len(issues)} warning(s).", file=sys.stderr)
    else:
        print("OK")
    return EXIT_OK


def _print_replay(
    session_id: str, *, event_log_store: FileEventLogStore, artifact_store: FileArtifactStore
) -> None:
    print(f"--- Replay session {session_id} ---")
    for event in event_log_store.read(session_id):
        if event.kind == EventKind.OPERATION_STARTED.value and event.payload.get("op_kind") == OpKind.CHAT.value:
            ref_raw = event.payload.get("input_ref")
            if isinstance(ref_raw, dict):
                try:
                    text = artifact_store.open_locator(str(ref_raw.get("locator")))
                    rendered = text.decode("utf-8", errors="replace").rstrip()
                    print(f"You: {rendered}")
                except Exception:
                    pass
        if event.kind == EventKind.LLM_RESPONSE_COMPLETED.value:
            ref_raw = event.payload.get("output_ref")
            if isinstance(ref_raw, dict):
                try:
                    text = artifact_store.open_locator(str(ref_raw.get("locator")))
                    rendered = text.decode("utf-8", errors="replace").rstrip()
                    print(f"Assistant: {rendered}")
                except Exception:
                    pass
    print("--- End replay ---")


def _emit_replay_to_ui(
    session_id: str,
    *,
    ui,
    event_log_store: FileEventLogStore,
    artifact_store: FileArtifactStore,
) -> None:
    from .ui.console_ui import UIEvent, UIEventKind

    ui.emit(UIEvent(UIEventKind.LOG, {"level": "replay", "message": f"--- Replay session {session_id} ---"}))
    for event in event_log_store.read(session_id):
        if event.kind == EventKind.OPERATION_STARTED.value and event.payload.get("op_kind") == OpKind.CHAT.value:
            ref_raw = event.payload.get("input_ref")
            if isinstance(ref_raw, dict):
                try:
                    text = artifact_store.open_locator(str(ref_raw.get("locator")))
                    rendered = text.decode("utf-8", errors="replace").rstrip()
                    ui.emit(UIEvent(UIEventKind.USER_SUBMITTED, {"text": rendered}))
                except Exception:
                    pass
        if event.kind == EventKind.LLM_RESPONSE_COMPLETED.value:
            ref_raw = event.payload.get("output_ref")
            if isinstance(ref_raw, dict):
                try:
                    text = artifact_store.open_locator(str(ref_raw.get("locator")))
                    rendered = text.decode("utf-8", errors="replace").rstrip()
                    ui.emit(UIEvent(UIEventKind.ASSISTANT_DELTA, {"text": rendered}))
                    ui.emit(UIEvent(UIEventKind.ASSISTANT_COMPLETED, {"finish_reason": None}))
                except Exception:
                    pass
    ui.emit(UIEvent(UIEventKind.LOG, {"level": "replay", "message": "--- End replay ---"}))


def _runtime_event_to_ui_events(event, *, think_parser) -> list:
    """
    Runtime Event -> UIEvent(s).

    This keeps the UI decoupled: only this adapter knows about runtime EventKind payloads.
    """

    from .ui.console_ui import UIEvent, UIEventKind

    out: list[UIEvent] = []
    kind = event.kind
    payload = event.payload if isinstance(event.payload, dict) else {}

    if kind == EventKind.LLM_REQUEST_STARTED.value:
        try:
            think_parser.reset()
        except Exception:
            pass
        out.append(UIEvent(UIEventKind.LLM_REQUEST_STARTED, {"request_id": event.request_id}))
        return out

    if kind == EventKind.LLM_THINKING_DELTA.value:
        delta = str(payload.get("thinking_delta") or "")
        if delta:
            out.append(UIEvent(UIEventKind.THINKING_DELTA, {"text": delta}))
        return out

    if kind == EventKind.LLM_RESPONSE_DELTA.value:
        delta = str(payload.get("text_delta") or "")
        if not delta:
            return out
        try:
            segments = think_parser.feed(delta)
        except Exception:
            segments = [(False, delta)]
        for is_think, text in segments:
            if not text:
                continue
            if is_think:
                out.append(UIEvent(UIEventKind.THINKING_DELTA, {"text": text}))
            else:
                out.append(UIEvent(UIEventKind.ASSISTANT_DELTA, {"text": text}))
        return out

    if kind == EventKind.LLM_RESPONSE_COMPLETED.value:
        out.append(UIEvent(UIEventKind.ASSISTANT_COMPLETED, {"finish_reason": payload.get("finish_reason")}))
        return out

    if kind == EventKind.TOOL_CALL_START.value:
        out.append(
            UIEvent(
                UIEventKind.TOOL_CALL_STARTED,
                {"tool": payload.get("tool_name") or "tool", "call_id": payload.get("tool_call_id"), "summary": None},
            )
        )
        return out

    if kind == EventKind.TOOL_CALL_END.value:
        out.append(
            UIEvent(
                UIEventKind.TOOL_CALL_COMPLETED,
                {
                    "tool": payload.get("tool_name") or "tool",
                    "call_id": payload.get("tool_call_id"),
                    "ok": not bool(payload.get("error")),
                },
            )
        )
        return out

    if kind == EventKind.OPERATION_PROGRESS.value:
        msg = payload.get("message")
        if msg:
            out.append(UIEvent(UIEventKind.PROGRESS, {"label": str(msg)}))
        return out

    if kind == EventKind.APPROVAL_REQUIRED.value:
        approval_id = payload.get("approval_id") or ""
        summary = payload.get("action_summary") or ""
        out.append(UIEvent(UIEventKind.WARNING, {"message": f"[approval] {approval_id}: {summary}".strip()}))
        return out

    if kind == EventKind.OPERATION_CANCELLED.value:
        reason = payload.get("reason") or "cancelled"
        out.append(UIEvent(UIEventKind.CANCELLED, {"message": str(reason)}))
        return out

    if kind == EventKind.LLM_REQUEST_FAILED.value:
        out.append(
            UIEvent(
                UIEventKind.ERROR_RAISED,
                {
                    "code": payload.get("error_code") or payload.get("code") or "llm_request_failed",
                    "message": payload.get("error") or str(payload),
                    "recoverable": bool(payload.get("retryable", True)),
                },
            )
        )
        return out

    if kind == EventKind.OPERATION_FAILED.value:
        out.append(
            UIEvent(
                UIEventKind.ERROR_RAISED,
                {
                    "code": payload.get("error_code") or "operation_failed",
                    "message": payload.get("error") or str(payload),
                    "recoverable": False,
                },
            )
        )
        return out

    return out


def _handle_pending_approvals(
    *,
    orchestrator: Orchestrator,
    session_id: str,
    approval_store: FileApprovalStore,
    timeout_s: float | None,
    request_id: str | None = None,
) -> None:
    while True:
        pending = approval_store.list(
            session_id=session_id,
            status=ApprovalStatus.PENDING,
            request_id=request_id,
        )
        if not pending:
            return

        record = pending[0]
        print()
        print(f"Approval required: {record.approval_id}")
        print(f"Summary: {record.action_summary}")
        if record.risk_level is not None:
            print(f"Risk: {record.risk_level}")
        if record.reason:
            print(f"Reason: {record.reason}")
        if record.diff_ref:
            try:
                ref = ArtifactRef.from_dict(record.diff_ref)
                raw = orchestrator.artifact_store.get(ref)
                diff_text = raw.decode("utf-8", errors="replace")
                max_chars = 8000
                print("\n--- Diff (preview) ---")
                if len(diff_text) > max_chars:
                    print(diff_text[:max_chars])
                    print(f"... (truncated, {len(diff_text)} chars total)")
                else:
                    print(diff_text)
                print("--- End diff ---")
            except Exception as e:
                print(f"(Failed to load diff: {e})", file=sys.stderr)
        while True:
            try:
                ans = input("Decision [approve/deny] (a/d): ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print("\nApproval decision interrupted; leaving approval pending.", file=sys.stderr)
                return
            if ans in {"approve", "a", "yes", "y"}:
                decision = "approve"
                break
            if ans in {"deny", "d", "no", "n", "abort"}:
                decision = "deny"
                break
            print("Invalid decision. Enter 'approve' or 'deny'.")

        decision_op = Op(
            kind=OpKind.APPROVAL_DECISION.value,
            payload={"approval_id": record.approval_id, "decision": decision},
            session_id=session_id,
            request_id=new_id("req"),
            timestamp=now_ts_ms(),
            turn_id=new_id("turn"),
        )
        orchestrator.handle(decision_op, timeout_s=timeout_s)


def _cmd_init(args: argparse.Namespace) -> int:
    project_root = Path(args.path).expanduser().resolve()

    if project_root.exists() and not project_root.is_dir():
        print(f"Error: path exists and is not a directory: {project_root}", file=sys.stderr)
        return EXIT_ERROR

    project_root.mkdir(parents=True, exist_ok=True)

    author_dirs = [
        project_root / "spec",
        project_root / "outline",
        project_root / "chapters",
        project_root / "drafts",
        project_root / "refs" / "style",
        project_root / "refs" / "research",
        project_root / "skills",
        project_root / "recipes",
    ]
    system_dirs = [
        project_root / ".novelaire" / "config",
        project_root / ".novelaire" / "policy",
        project_root / ".novelaire" / "sessions",
        project_root / ".novelaire" / "events",
        project_root / ".novelaire" / "artifacts",
        project_root / ".novelaire" / "state",
        project_root / ".novelaire" / "index",
        project_root / ".novelaire" / "cache",
        project_root / ".novelaire" / "tmp",
    ]

    for directory in [*author_dirs, *system_dirs]:
        directory.mkdir(parents=True, exist_ok=True)

    env_path = project_root / ".novelaire" / "config" / "env"
    if not env_path.exists():
        env_path.write_text(
            "\n".join(
                [
                    "# Novelaire project configuration (v0.1)",
                    "#",
                    "# Fill at least one provider config, then run:",
                    "#   python -m novelaire chat",
                    "#",
                    "# Required:",
                    "#   NOVELAIRE_PROVIDER_KIND   = openai_compatible | anthropic",
                    "#   NOVELAIRE_BASE_URL        = endpoint base URL",
                    "#   NOVELAIRE_MODEL           = model name",
                    "# Optional:",
                    "#   NOVELAIRE_API_KEY         = API key (allowed as plaintext in this local-only workflow)",
                    "#   NOVELAIRE_TIMEOUT_S       = per-request timeout seconds",
                    "#   NOVELAIRE_MAX_TOKENS      = max output tokens (REQUIRED for anthropic)",
                    "#   NOVELAIRE_SUPPORTS_TOOLS  = 0/1",
                    "",
                    "# --- OpenAI-compatible example (vLLM/TGI/llama.cpp/OpenAI/OpenRouter proxy etc.) ---",
                    "NOVELAIRE_PROVIDER_KIND=openai_compatible",
                    "NOVELAIRE_BASE_URL=http://127.0.0.1:8000/v1",
                    "NOVELAIRE_MODEL=your-model-name",
                    "# NOVELAIRE_API_KEY=replace-me  # optional for many local/proxied endpoints",
                    "NOVELAIRE_TIMEOUT_S=60",
                    "",
                    "# --- Anthropic example ---",
                    "# NOVELAIRE_PROVIDER_KIND=anthropic",
                    "# NOVELAIRE_BASE_URL=https://api.anthropic.com",
                    "# NOVELAIRE_MODEL=claude-3-5-sonnet-20241022",
                    "# NOVELAIRE_API_KEY=replace-me",
                    "# NOVELAIRE_MAX_TOKENS=1024",
                    "",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

    print(f"Initialized Novelaire project at {project_root}")
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    _configure_text_io()
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        func = getattr(args, "func")
        return int(func(args))
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130


def _export_extra_runtime_dirs(*, bundle_dir: Path, config_dir: Path, policy_dir: Path, state_dir: Path) -> None:
    target_root = bundle_dir / ".novelaire"
    _copy_tree(config_dir, target_root / "config")
    _copy_tree(policy_dir, target_root / "policy")
    _copy_tree(state_dir, target_root / "state")


def _copy_tree(src: Path, dst: Path) -> None:
    if not src.exists():
        return
    if src.is_dir():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src, dst, dirs_exist_ok=True)
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)


def _export_approval_artifacts(
    *,
    session_id: str,
    approval_store: FileApprovalStore,
    artifact_store: FileArtifactStore,
    bundle_artifacts_dir: Path,
) -> None:
    bundle_artifacts_dir.mkdir(parents=True, exist_ok=True)
    approvals = approval_store.list(session_id=session_id, status=None, request_id=None)
    seen: set[str] = set()
    for rec in approvals:
        for ref in _iter_artifact_refs(rec.to_dict()):
            if ref.artifact_id in seen:
                continue
            seen.add(ref.artifact_id)
            src = artifact_store.resolve_path(ref)
            dst = bundle_artifacts_dir / Path(ref.locator).name
            if dst.exists():
                continue
            if src.exists() and src.is_file():
                shutil.copyfile(src, dst)


def _iter_artifact_refs(value: object) -> list[ArtifactRef]:
    out: list[ArtifactRef] = []
    required = {"artifact_id", "artifact_kind", "locator", "created_at"}
    if isinstance(value, dict):
        if required <= set(value.keys()):
            try:
                out.append(ArtifactRef.from_dict(value))
            except Exception:
                pass
        for v in value.values():
            out.extend(_iter_artifact_refs(v))
        return out
    if isinstance(value, list):
        for item in value:
            out.extend(_iter_artifact_refs(item))
        return out
    return out
