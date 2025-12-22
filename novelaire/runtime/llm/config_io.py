from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .config import ModelConfig, ModelConfigLayers
from .errors import ModelConfigError
from .types import (
    CredentialRef,
    ModelCapabilities,
    ModelLimits,
    ModelProfile,
    ModelRole,
    ProviderKind,
)


def default_global_models_path() -> Path:
    override = os.environ.get("NOVELAIRE_GLOBAL_MODELS_PATH")
    if override:
        return Path(os.path.expanduser(override))
    return Path.home() / ".novelaire" / "config" / "models.json"


def project_models_path(project_root: Path) -> Path:
    override = os.environ.get("NOVELAIRE_PROJECT_MODELS_PATH")
    if override:
        path = Path(os.path.expanduser(override))
        if not path.is_absolute():
            path = project_root / path
        return path
    return project_root / ".novelaire" / "config" / "models.json"


def discover_project_root(start_dir: Path) -> Path | None:
    current = start_dir.resolve()
    while True:
        if (current / ".novelaire").is_dir():
            return current
        if current.parent == current:
            return None
        current = current.parent


def load_model_config_file(path: Path) -> ModelConfig:
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError as e:
        raise ModelConfigError(f"Model config file not found: {path}") from e
    except OSError as e:
        raise ModelConfigError(f"Failed to read model config file: {path} ({e})") from e

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ModelConfigError(f"Model config file is not valid JSON: {path} ({e})") from e

    return load_model_config_dict(data, source=str(path))


def save_model_config_file(path: Path, config: ModelConfig) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = model_config_to_dict(config)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_model_config_layers_for_dir(
    start_dir: Path | None = None,
    *,
    global_path: Path | None = None,
    require_project: bool = True,
) -> ModelConfigLayers:
    start_dir = (start_dir or Path.cwd()).resolve()
    global_path = global_path or default_global_models_path()

    global_cfg = ModelConfig()
    if global_path.exists():
        global_cfg = load_model_config_file(global_path)

    project_root = discover_project_root(start_dir)
    if project_root is None:
        if require_project:
            raise ModelConfigError(
                "No Novelaire project found (missing '.novelaire' directory). "
                "Run 'novelaire init' or pass an explicit project root."
            )
        return ModelConfigLayers(global_config=global_cfg)

    project_path = project_models_path(project_root)
    if not project_path.exists():
        if require_project:
            raise ModelConfigError(
                f"Missing required project model config file: {project_path}. "
                "Create it under '.novelaire/config/models.json'."
            )
        return ModelConfigLayers(global_config=global_cfg)

    return ModelConfigLayers(global_config=global_cfg, project_config=load_model_config_file(project_path))


def load_model_config_dict(data: Any, *, source: str) -> ModelConfig:
    root = _ensure_dict(data, ctx=f"{source}:root")
    _assert_known_keys(root, allowed={"profiles", "role_pointers"}, ctx=f"{source}:root")

    profiles_raw = root.get("profiles", {})
    profiles_obj = _ensure_dict(profiles_raw, ctx=f"{source}:profiles")
    profiles: dict[str, ModelProfile] = {}
    for profile_id, profile_data in profiles_obj.items():
        if not isinstance(profile_id, str) or not profile_id:
            raise ModelConfigError(f"{source}:profiles: profile id must be a non-empty string")
        profile_dict = _ensure_dict(profile_data, ctx=f"{source}:profiles.{profile_id}")
        profiles[profile_id] = _parse_profile(profile_id, profile_dict, source=source)

    role_pointers_raw = root.get("role_pointers", {})
    role_pointers_obj = _ensure_dict(role_pointers_raw, ctx=f"{source}:role_pointers")
    role_pointers: dict[ModelRole, str] = {}
    for role_key, profile_id in role_pointers_obj.items():
        if not isinstance(role_key, str) or not role_key:
            raise ModelConfigError(f"{source}:role_pointers: role key must be a non-empty string")
        if not isinstance(profile_id, str) or not profile_id:
            raise ModelConfigError(
                f"{source}:role_pointers.{role_key}: profile id must be a non-empty string"
            )
        try:
            role = ModelRole(role_key)
        except ValueError as e:
            raise ModelConfigError(f"{source}:role_pointers: unknown role '{role_key}'") from e
        role_pointers[role] = profile_id

    return ModelConfig(profiles=profiles, role_pointers=role_pointers)


def model_config_to_dict(config: ModelConfig) -> dict[str, Any]:
    profiles: dict[str, Any] = {}
    for profile_id, profile in config.profiles.items():
        profiles[profile_id] = _profile_to_dict(profile)

    role_pointers = {role.value: profile_id for role, profile_id in config.role_pointers.items()}
    return {
        "profiles": profiles,
        "role_pointers": role_pointers,
    }


def _parse_profile(profile_id: str, profile_dict: dict[str, Any], *, source: str) -> ModelProfile:
    _assert_known_keys(
        profile_dict,
        allowed={
            "provider_kind",
            "base_url",
            "model_name",
            "credential_ref",
            "default_params",
            "capabilities",
            "tags",
            "limits",
            "profile_id",
        },
        ctx=f"{source}:profiles.{profile_id}",
    )

    explicit_id = profile_dict.get("profile_id")
    if explicit_id is not None and explicit_id != profile_id:
        raise ModelConfigError(
            f"{source}:profiles.{profile_id}: profile_id mismatch (got {explicit_id!r})"
        )

    provider_kind_str = _require_str(
        profile_dict, "provider_kind", ctx=f"{source}:profiles.{profile_id}"
    )
    try:
        provider_kind = ProviderKind(provider_kind_str)
    except ValueError as e:
        raise ModelConfigError(
            f"{source}:profiles.{profile_id}: unknown provider_kind '{provider_kind_str}'"
        ) from e

    base_url = _require_str(profile_dict, "base_url", ctx=f"{source}:profiles.{profile_id}")
    model_name = _require_str(profile_dict, "model_name", ctx=f"{source}:profiles.{profile_id}")

    credential_ref = None
    if "credential_ref" in profile_dict and profile_dict["credential_ref"] is not None:
        cred = _ensure_dict(profile_dict["credential_ref"], ctx=f"{source}:profiles.{profile_id}.credential_ref")
        _assert_known_keys(cred, allowed={"kind", "identifier"}, ctx=f"{source}:profiles.{profile_id}.credential_ref")
        kind = _require_str(cred, "kind", ctx=f"{source}:profiles.{profile_id}.credential_ref")
        ident = _require_str(cred, "identifier", ctx=f"{source}:profiles.{profile_id}.credential_ref")
        credential_ref = CredentialRef(kind=kind, identifier=ident)

    default_params: dict[str, Any] = {}
    if "default_params" in profile_dict and profile_dict["default_params"] is not None:
        default_params_obj = _ensure_dict(profile_dict["default_params"], ctx=f"{source}:profiles.{profile_id}.default_params")
        default_params = dict(default_params_obj)

    capabilities = ModelCapabilities()
    if "capabilities" in profile_dict and profile_dict["capabilities"] is not None:
        cap = _ensure_dict(profile_dict["capabilities"], ctx=f"{source}:profiles.{profile_id}.capabilities")
        _assert_known_keys(
            cap,
            allowed={"supports_tools", "supports_structured_output", "supports_streaming"},
            ctx=f"{source}:profiles.{profile_id}.capabilities",
        )
        capabilities = ModelCapabilities(
            supports_tools=_maybe_bool(
                cap.get("supports_tools"), ctx=f"{source}:profiles.{profile_id}.capabilities.supports_tools"
            ),
            supports_structured_output=_maybe_bool(
                cap.get("supports_structured_output"),
                ctx=f"{source}:profiles.{profile_id}.capabilities.supports_structured_output",
            ),
            supports_streaming=_maybe_bool(
                cap.get("supports_streaming"),
                ctx=f"{source}:profiles.{profile_id}.capabilities.supports_streaming",
            ),
        )

    tags: set[str] = set()
    if "tags" in profile_dict and profile_dict["tags"] is not None:
        tags_raw = profile_dict["tags"]
        if not isinstance(tags_raw, list) or not all(isinstance(t, str) and t for t in tags_raw):
            raise ModelConfigError(f"{source}:profiles.{profile_id}.tags must be a list of strings")
        tags = set(tags_raw)

    limits = None
    if "limits" in profile_dict and profile_dict["limits"] is not None:
        lim = _ensure_dict(profile_dict["limits"], ctx=f"{source}:profiles.{profile_id}.limits")
        _assert_known_keys(
            lim,
            allowed={"context_limit_tokens", "max_output_tokens"},
            ctx=f"{source}:profiles.{profile_id}.limits",
        )
        limits = ModelLimits(
            context_limit_tokens=_maybe_int(
                lim.get("context_limit_tokens"),
                ctx=f"{source}:profiles.{profile_id}.limits.context_limit_tokens",
            ),
            max_output_tokens=_maybe_int(
                lim.get("max_output_tokens"),
                ctx=f"{source}:profiles.{profile_id}.limits.max_output_tokens",
            ),
        )

    return ModelProfile(
        profile_id=profile_id,
        provider_kind=provider_kind,
        base_url=base_url,
        model_name=model_name,
        credential_ref=credential_ref,
        default_params=default_params,
        capabilities=capabilities,
        tags=tags,
        limits=limits,
    )


def _profile_to_dict(profile: ModelProfile) -> dict[str, Any]:
    out: dict[str, Any] = {
        "provider_kind": profile.provider_kind.value,
        "base_url": profile.base_url,
        "model_name": profile.model_name,
    }
    if profile.credential_ref is not None:
        out["credential_ref"] = {
            "kind": profile.credential_ref.kind,
            "identifier": profile.credential_ref.identifier,
        }
    if profile.default_params:
        out["default_params"] = dict(profile.default_params)

    caps = profile.capabilities
    caps_dict: dict[str, Any] = {}
    if caps.supports_tools is not None:
        caps_dict["supports_tools"] = caps.supports_tools
    if caps.supports_structured_output is not None:
        caps_dict["supports_structured_output"] = caps.supports_structured_output
    if caps.supports_streaming is not None:
        caps_dict["supports_streaming"] = caps.supports_streaming
    if caps_dict:
        out["capabilities"] = caps_dict

    if profile.tags:
        out["tags"] = sorted(profile.tags)

    if profile.limits is not None and (
        profile.limits.context_limit_tokens is not None
        or profile.limits.max_output_tokens is not None
    ):
        limits: dict[str, Any] = {}
        if profile.limits.context_limit_tokens is not None:
            limits["context_limit_tokens"] = profile.limits.context_limit_tokens
        if profile.limits.max_output_tokens is not None:
            limits["max_output_tokens"] = profile.limits.max_output_tokens
        out["limits"] = limits

    return out


def _ensure_dict(value: Any, *, ctx: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ModelConfigError(f"{ctx} must be an object")
    return value


def _require_str(obj: dict[str, Any], key: str, *, ctx: str) -> str:
    val = obj.get(key)
    if not isinstance(val, str) or not val.strip():
        raise ModelConfigError(f"{ctx}.{key} must be a non-empty string")
    return val


def _maybe_bool(value: Any, *, ctx: str) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    raise ModelConfigError(f"{ctx} must be a boolean or null")


def _maybe_int(value: Any, *, ctx: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    raise ModelConfigError(f"{ctx} must be an integer or null")


def _assert_known_keys(obj: dict[str, Any], *, allowed: set[str], ctx: str) -> None:
    unknown = set(obj.keys()) - allowed
    if unknown:
        rendered = ", ".join(sorted(unknown))
        raise ModelConfigError(f"{ctx} contains unknown keys: {rendered}")
