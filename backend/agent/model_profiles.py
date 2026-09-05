"""Logical RECLAIM model profiles and safe LiteLLM provider construction."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlparse

from packages.contracts.analysis_policy import ModelBudget, ProviderMode

from .litellm_gateway import LiteLLMProviderAdapter
from .providers import ModelProvider

MODEL_PROFILE_VERSION = "reclaim-model-profiles-v1.0.0"


class ModelProfileError(ValueError):
    """A model profile is malformed or unsafe to resolve."""


class ModelProfileUnavailable(ModelProfileError):
    """A configured profile has no usable model endpoint/artifact."""


@dataclass(frozen=True, slots=True)
class ModelProfile:
    name: str
    provider: str
    model: str
    mode: ProviderMode = ProviderMode.LIVE
    api_base: str | None = None
    api_key: str | None = None
    enabled: bool = True
    profile_version: str = MODEL_PROFILE_VERSION
    fallback_profile: str | None = None

    def __post_init__(self) -> None:
        for field in ("name", "provider", "model", "profile_version"):
            if not isinstance(getattr(self, field), str) or not getattr(self, field).strip():
                raise ModelProfileError(f"model profile {field} is required")
        if self.api_base is not None:
            _validate_endpoint(self.api_base)
        if self.api_key is not None and not self.api_key.strip():
            raise ModelProfileError("model profile API key cannot be blank")


def resolve_profile(
    name: str = "reclaim-specialist",
    *,
    environ: Mapping[str, str] | None = None,
) -> ModelProfile:
    """Resolve one allowlisted logical profile without returning secret values."""

    env = dict(os.environ if environ is None else environ)
    normalized = name.strip().lower()
    if normalized not in {"reclaim-specialist", "reclaim-baseline", "reclaim-cloud-fallback"}:
        raise ModelProfileError(f"unknown RECLAIM model profile: {name}")

    if normalized == "reclaim-specialist":
        model = env.get("RECLAIM_SPECIALIST_MODEL", "").strip()
        endpoint = env.get("RECLAIM_SPECIALIST_API_BASE", "http://127.0.0.1:8003/v1").strip()
        enabled = _env_bool(env, "RECLAIM_SPECIALIST_ENABLED", bool(model))
        if not model:
            raise ModelProfileUnavailable(
                "reclaim-specialist is unavailable: RECLAIM_SPECIALIST_MODEL is not configured"
            )
        fallback_profile = _optional(env.get("RECLAIM_AGENT_FALLBACK_PROFILE"))
        if fallback_profile is not None and fallback_profile.strip().lower() == normalized:
            raise ModelProfileError("fresh-agent fallback profile creates a cycle")
        return ModelProfile(
            name=normalized,
            provider="openai-compatible-local",
            model=model,
            api_base=endpoint,
            enabled=enabled,
            fallback_profile=fallback_profile,
        )

    if normalized == "reclaim-baseline":
        model = env.get("RECLAIM_BASELINE_MODEL", "HuggingFaceTB/SmolLM2-135M-Instruct").strip()
        endpoint = _optional(env.get("RECLAIM_BASELINE_API_BASE"))
        return ModelProfile(
            name=normalized,
            provider="openai-compatible-baseline" if endpoint else "litellm",
            model=model,
            api_base=endpoint,
            enabled=_env_bool(env, "RECLAIM_BASELINE_ENABLED", True),
        )

    provider = env.get("RECLAIM_CLOUD_PROVIDER", "").strip()
    model = env.get("RECLAIM_CLOUD_MODEL", "").strip()
    if not provider or not model:
        raise ModelProfileUnavailable(
            "reclaim-cloud-fallback is unavailable: provider/model configuration is missing"
        )
    key_name = env.get("RECLAIM_CLOUD_API_KEY_ENV", "").strip()
    key = env.get(key_name, "") if key_name else ""
    if not key:
        raise ModelProfileUnavailable(
            "reclaim-cloud-fallback is unavailable: configured key is missing"
        )
    return ModelProfile(
        name=normalized,
        provider=provider,
        model=model,
        api_key=key,
        api_base=_optional(env.get("RECLAIM_CLOUD_API_BASE")),
        enabled=True,
    )


def build_provider(
    profile: ModelProfile,
    *,
    completion: object | None = None,
) -> ModelProvider:
    """Build the existing LiteLLM adapter for a resolved profile."""

    if not isinstance(profile, ModelProfile):
        raise TypeError("build_provider requires a ModelProfile")
    if not profile.enabled:
        raise ModelProfileUnavailable(f"model profile is disabled: {profile.name}")
    kwargs = {
        "provider": profile.provider,
        "model": profile.model,
        "mode": profile.mode,
        "api_base": profile.api_base,
        "api_key": profile.api_key,
        "transport_model": (
            f"openai/{profile.model}"
            if profile.api_base and profile.provider.startswith("openai-compatible")
            else None
        ),
    }
    if completion is not None:
        kwargs["completion"] = completion
    return LiteLLMProviderAdapter(**kwargs)  # type: ignore[arg-type]


def profile_budget(environ: Mapping[str, str] | None = None) -> ModelBudget:
    env = dict(os.environ if environ is None else environ)
    return ModelBudget(
        max_tokens=_env_int(env, "RECLAIM_AGENT_MAX_TOKENS", 2048, 1, 100_000),
        max_tool_calls=_env_int(env, "RECLAIM_AGENT_MAX_TOOL_CALLS", 4, 0, 100),
        timeout_seconds=_env_int(env, "RECLAIM_AGENT_TIMEOUT_SECONDS", 60, 1, 900),
    )


def _validate_endpoint(value: str) -> None:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ModelProfileError("model profile endpoint must be an HTTP(S) URL")
    if parsed.username or parsed.password:
        raise ModelProfileError("model profile endpoint cannot embed credentials")


def _optional(value: str | None) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _env_bool(env: Mapping[str, str], name: str, default: bool) -> bool:
    value = env.get(name)
    return default if value is None else value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(env: Mapping[str, str], name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(env.get(name, str(default)))
    except ValueError as exc:
        raise ModelProfileError(f"{name} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise ModelProfileError(f"{name} is outside the allowed range")
    return value


__all__ = [
    "MODEL_PROFILE_VERSION",
    "ModelProfile",
    "ModelProfileError",
    "ModelProfileUnavailable",
    "build_provider",
    "profile_budget",
    "resolve_profile",
]
