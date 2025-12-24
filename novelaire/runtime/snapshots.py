from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path


class SnapshotError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class SnapshotResult:
    commit: str
    label: str | None = None


class GitSnapshotBackend:
    """
    Internal Git-backed snapshot backend.

    Uses an internal git-dir under `.novelaire/state/git` and always calls git with
    explicit `--git-dir` and `--work-tree` to avoid touching any user `.git`.
    """

    def __init__(self, *, project_root: Path, git_dir: Path | None = None) -> None:
        self._project_root = project_root.expanduser().resolve()
        self._git_dir = (git_dir or (self._project_root / ".novelaire" / "state" / "git")).expanduser().resolve()

    @property
    def git_dir(self) -> Path:
        return self._git_dir

    def snapshot_create(self, *, reason: str) -> SnapshotResult:
        self._ensure_repo()
        self._ensure_excludes()
        self._git("add", "-A")
        msg = f"snapshot: {reason}".strip()
        if not msg:
            msg = "snapshot"
        self._git("commit", "-m", msg, "--allow-empty")
        commit = self._git_stdout("rev-parse", "HEAD").strip()
        return SnapshotResult(commit=commit)

    def snapshot_label(self, *, label: str) -> SnapshotResult:
        self._ensure_repo()
        label = label.strip()
        if not label:
            raise SnapshotError("Missing label.")
        self._git("tag", "-f", label)
        commit = self._git_stdout("rev-parse", "HEAD").strip()
        return SnapshotResult(commit=commit, label=label)

    def snapshot_diff(self, *, a: str, b: str) -> str:
        self._ensure_repo()
        return self._git_stdout("diff", a, b)

    def snapshot_rollback(self, *, target: str) -> None:
        self._ensure_repo()
        self._git("reset", "--hard", target)

    def _ensure_repo(self) -> None:
        self._git_dir.mkdir(parents=True, exist_ok=True)
        head = self._git_dir / "HEAD"
        if not head.exists():
            self._git("init")
            self._git("config", "user.name", "Novelaire")
            self._git("config", "user.email", "novelaire@local")
        self._ensure_excludes()

    def _ensure_excludes(self) -> None:
        info = self._git_dir / "info"
        info.mkdir(parents=True, exist_ok=True)
        exclude = info / "exclude"
        patterns = [
            ".novelaire/state/git/",
            ".novelaire/cache/",
            ".novelaire/index/",
            ".novelaire/tmp/",
            ".novelaire/events/",
            ".novelaire/sessions/",
            ".novelaire/artifacts/",
        ]
        existing = ""
        if exclude.exists():
            try:
                existing = exclude.read_text(encoding="utf-8", errors="replace")
            except OSError:
                existing = ""
        lines = [ln.strip() for ln in existing.splitlines() if ln.strip()]
        changed = False
        for pat in patterns:
            if pat not in lines:
                lines.append(pat)
                changed = True
        if changed or not exclude.exists():
            exclude.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _git(self, *args: str) -> None:
        self._run_git(args, capture=False)

    def _git_stdout(self, *args: str) -> str:
        return self._run_git(args, capture=True)

    def _run_git(self, args: tuple[str, ...] | list[str], *, capture: bool) -> str:
        cmd = ["git", f"--git-dir={self._git_dir}", f"--work-tree={self._project_root}", *args]
        env = dict(os.environ)
        env.update({"GIT_TERMINAL_PROMPT": "0"})
        try:
            proc = subprocess.run(
                cmd,
                check=False,
                capture_output=capture,
                text=True,
                env=env,
            )
        except FileNotFoundError as e:
            raise SnapshotError("git executable not found.") from e
        if proc.returncode != 0:
            stderr = proc.stderr.strip() if proc.stderr else ""
            raise SnapshotError(f"git failed ({proc.returncode}): {' '.join(args)}\n{stderr}".rstrip())
        return proc.stdout or ""

