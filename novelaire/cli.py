from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__


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
    chat_parser.set_defaults(func=_cmd_not_implemented)

    session_parser = subparsers.add_parser("session", help="Manage sessions.")
    session_subparsers = session_parser.add_subparsers(dest="session_cmd", required=True)
    session_list_parser = session_subparsers.add_parser("list", help="List sessions.")
    session_list_parser.set_defaults(func=_cmd_not_implemented)
    session_resume_parser = session_subparsers.add_parser("resume", help="Resume a session.")
    session_resume_parser.add_argument("session_id", help="Session ID to resume.")
    session_resume_parser.set_defaults(func=_cmd_not_implemented)

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
    debug_export_parser.set_defaults(func=_cmd_not_implemented)

    return parser


def _cmd_not_implemented(_: argparse.Namespace) -> int:
    print("Not implemented yet.", file=sys.stderr)
    return 1


def _cmd_init(args: argparse.Namespace) -> int:
    project_root = Path(args.path).expanduser().resolve()

    if project_root.exists() and not project_root.is_dir():
        print(f"Error: path exists and is not a directory: {project_root}", file=sys.stderr)
        return 1

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

    print(f"Initialized Novelaire project at {project_root}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        func = getattr(args, "func")
        return int(func(args))
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130

