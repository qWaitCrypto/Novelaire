from __future__ import annotations

import re
import shutil
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .frontmatter import FrontmatterError, parse_markdown_frontmatter


@dataclass(frozen=True, slots=True)
class SkillMetadata:
    name: str
    description: str
    skill_dir: Path
    skill_md_path: Path
    allowed_tools: list[str] | None = None
    metadata: dict[str, str] | None = None

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
        }


@dataclass(frozen=True, slots=True)
class LoadedSkill:
    meta: SkillMetadata
    instructions: str
    resources: list[str]

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "name": self.meta.name,
            "description": self.meta.description,
            "allowed_tools": list(self.meta.allowed_tools) if self.meta.allowed_tools is not None else None,
            "metadata": dict(self.meta.metadata) if self.meta.metadata is not None else None,
            "instructions": self.instructions,
            "resources": list(self.resources),
        }


class SkillStore:
    def __init__(self, *, project_root: Path) -> None:
        self._project_root = project_root.expanduser().resolve()
        self._skills_root = self._project_root / ".novelaire" / "skills"
        self._by_name: dict[str, SkillMetadata] = {}
        self._warnings: list[str] = []
        self.refresh()

    @property
    def warnings(self) -> list[str]:
        return list(self._warnings)

    def refresh(self) -> None:
        self._by_name = {}
        self._warnings = []

        if not self._skills_root.exists():
            return

        if not self._skills_root.is_dir():
            self._warnings.append("Skills root is not a directory: .novelaire/skills")
            return

        skill_files: list[Path] = []
        # Prefer SKILL.md when both exist in a directory; accept skill.md as fallback.
        seen_dirs: set[Path] = set()
        for skill_md in sorted(self._skills_root.rglob("SKILL.md")):
            try:
                if not skill_md.is_file() or skill_md.is_symlink():
                    continue
            except OSError:
                continue
            seen_dirs.add(skill_md.parent.resolve())
            skill_files.append(skill_md)

        for skill_md in sorted(self._skills_root.rglob("skill.md")):
            try:
                if not skill_md.is_file() or skill_md.is_symlink():
                    continue
            except OSError:
                continue
            if skill_md.parent.resolve() in seen_dirs:
                continue
            skill_files.append(skill_md)

        for skill_md in skill_files:

            try:
                rel_dir = skill_md.parent.relative_to(self._skills_root)
            except Exception:
                continue

            if not rel_dir.parts:
                self._warnings.append("Ignored invalid skill at .novelaire/skills/SKILL.md (skill must be a directory).")
                continue

            if any(part.startswith(".") for part in rel_dir.parts):
                continue

            try:
                raw = skill_md.read_text(encoding="utf-8", errors="replace")
            except OSError as e:
                self._warnings.append(f"Failed to read skill: {skill_md}: {e}")
                continue

            try:
                parsed = parse_markdown_frontmatter(raw)
            except FrontmatterError as e:
                self._warnings.append(f"Failed to parse skill frontmatter: {skill_md}: {e}")
                continue

            description = parsed.data.get("description")
            if not isinstance(description, str) or not description.strip():
                self._warnings.append(f"Skipped skill missing description: {skill_md}")
                continue
            description = _sanitize_single_line(description.strip())
            if len(description) > 1024:
                self._warnings.append(f"Skipped skill with overly long description (>1024 chars): {skill_md}")
                continue

            name_raw = parsed.data.get("name")
            if not isinstance(name_raw, str) or not name_raw.strip():
                self._warnings.append(f"Skipped skill missing name: {skill_md}")
                continue
            name = _sanitize_single_line(name_raw.strip())

            dir_name = unicodedata.normalize("NFKC", skill_md.parent.name)
            if unicodedata.normalize("NFKC", name) != dir_name:
                self._warnings.append(
                    f"Skipped skill with name-directory mismatch at {skill_md}: name='{name}' dir='{skill_md.parent.name}'"
                )
                continue
            name_errors = _validate_skill_name(name)
            if name_errors:
                self._warnings.append(f"Skipped skill with invalid name at {skill_md}: {', '.join(name_errors)}")
                continue

            allowed_tools = _parse_allowed_tools(parsed.data)
            meta = _parse_metadata(parsed.data)

            if name in self._by_name:
                existing = self._by_name[name].skill_md_path
                self._warnings.append(f"Duplicate skill name '{name}' at {skill_md} (already have {existing}); keeping first.")
                continue

            self._by_name[name] = SkillMetadata(
                name=name,
                description=description.strip(),
                skill_dir=skill_md.parent,
                skill_md_path=skill_md,
                allowed_tools=allowed_tools,
                metadata=meta,
            )

    def list(self) -> list[SkillMetadata]:
        return [self._by_name[name] for name in sorted(self._by_name)]

    def get(self, name: str) -> SkillMetadata | None:
        return self._by_name.get(name)

    def load(self, name: str) -> LoadedSkill:
        meta = self._by_name.get(name)
        if meta is None:
            raise ValueError(f"Unknown skill: {name}")

        raw = meta.skill_md_path.read_text(encoding="utf-8", errors="replace")
        parsed = parse_markdown_frontmatter(raw)
        resources = _list_resources(meta.skill_dir)
        return LoadedSkill(meta=meta, instructions=parsed.body, resources=resources)


def seed_builtin_skills(*, project_root: Path) -> list[str]:
    """
    Seed the built-in skill library into `<project>/.novelaire/skills/`.

    Built-in skills are shipped as a directory tree under `novelaire/builtin/skills/`.
    Each skill is a directory containing `SKILL.md` plus optional resource files.

    This function is intentionally conservative: it never overwrites existing skill directories.
    """

    skills_root = project_root.expanduser().resolve() / ".novelaire" / "skills"
    skills_root.mkdir(parents=True, exist_ok=True)

    builtin_root = _builtin_skills_root()
    if not builtin_root.exists() or not builtin_root.is_dir():
        raise RuntimeError(f"Built-in skills root not found: {builtin_root}")

    skipped: list[str] = []
    for skill_md in sorted(builtin_root.rglob("SKILL.md")):
        try:
            rel_dir = skill_md.parent.relative_to(builtin_root)
        except Exception:
            continue
        if not rel_dir.parts:
            continue
        if any(part.startswith(".") for part in rel_dir.parts):
            continue
        target_dir = (skills_root / rel_dir).resolve()
        if target_dir.exists():
            skipped.append(str(Path(".novelaire/skills") / rel_dir))
            continue
        target_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(
            skill_md.parent,
            target_dir,
            dirs_exist_ok=False,
            ignore=shutil.ignore_patterns(".*"),
        )
    return skipped


def _parse_allowed_tools(frontmatter: dict[str, Any]) -> list[str] | None:
    raw = frontmatter.get("allowed-tools")
    if raw is None:
        raw = frontmatter.get("allowed_tools")
    if raw is None:
        return None
    out: list[str] = []
    if isinstance(raw, str):
        out.extend([part for part in raw.split() if part.strip()])
    elif isinstance(raw, list):
        for item in raw:
            if not isinstance(item, str):
                continue
            item = item.strip()
            if item:
                out.append(item)
    else:
        return None
    return out or None


def _parse_metadata(frontmatter: dict[str, Any]) -> dict[str, str] | None:
    raw = frontmatter.get("metadata")
    if raw is None:
        return None
    if not isinstance(raw, dict):
        return None
    out: dict[str, str] = {}
    for k, v in raw.items():
        out[str(k)] = str(v)
    return out or None


def _sanitize_single_line(raw: str) -> str:
    return " ".join(raw.split())


_NAME_RE = re.compile(r"^[^\W_](?:[^\W_]|-)*[^\W_]$|^[^\W_]$", re.UNICODE)


def _validate_skill_name(name: str) -> list[str]:
    """
    AgentSkills-style skill name validation.

    Notes:
    - Uses unicode-aware `isalnum`-equivalent character class (`\\w` minus `_`) to allow i18n names.
    - Enforces lowercase and hyphen rules.
    """

    errors: list[str] = []
    normalized = unicodedata.normalize("NFKC", name.strip())
    if not normalized:
        return ["name is empty"]
    if len(normalized) > 64:
        errors.append("name exceeds 64 characters")
    if normalized != normalized.lower():
        errors.append("name must be lowercase")
    if normalized.startswith("-") or normalized.endswith("-"):
        errors.append("name cannot start or end with '-'")
    if "--" in normalized:
        errors.append("name cannot contain consecutive hyphens ('--')")
    if not all(ch.isalnum() or ch == "-" for ch in normalized):
        errors.append("name contains invalid characters (only letters/digits/hyphens)")
    if not _NAME_RE.match(normalized):
        errors.append("name format is invalid")
    return errors


def _list_resources(skill_dir: Path) -> list[str]:
    out: list[str] = []
    for path in sorted(skill_dir.rglob("*")):
        try:
            if not path.is_file() or path.is_symlink():
                continue
        except OSError:
            continue
        if path.name == "SKILL.md":
            continue
        if any(part.startswith(".") for part in path.relative_to(skill_dir).parts):
            continue
        out.append(str(path.relative_to(skill_dir)))
    return out


def _builtin_skills_root() -> Path:
    package_root = Path(__file__).resolve().parent.parent
    return package_root / "builtin" / "skills"
