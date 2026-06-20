from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class SandboxConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True)
class SandboxRuntimePlan:
    enabled: bool
    backend: str
    sdk_supported: bool
    run_config: Any | None
    summary: dict[str, Any]


def sandbox_plan_from_environment(config: dict[str, Any] | None) -> SandboxRuntimePlan:
    env_config = dict(config or {})
    sandbox_config = dict(env_config.get("sandbox") or {})
    env_type = str(env_config.get("type") or "cloud")
    enabled = bool(sandbox_config.get("enabled", False))
    backend = str(sandbox_config.get("backend") or _default_backend_for_env(env_type))
    policy = _environment_policy_summary(env_config)

    if not enabled:
        return SandboxRuntimePlan(
            enabled=False,
            backend=backend,
            sdk_supported=False,
            run_config=None,
            summary={
                "enabled": False,
                "environment_type": env_type,
                "backend": backend,
                "reason": "sandbox is disabled for this environment",
                "policy": policy,
            },
        )

    if backend == "unix_local":
        run_config = _unix_local_run_config(sandbox_config)
        return SandboxRuntimePlan(
            enabled=True,
            backend=backend,
            sdk_supported=True,
            run_config=run_config,
            summary={
                "enabled": True,
                "environment_type": env_type,
                "backend": backend,
                "sdk": "openai_agents_sdk",
                "capabilities": sandbox_config.get("capabilities") or ["filesystem", "shell", "compaction"],
                "root": sandbox_config.get("root") or "/workspace",
                "policy": policy,
            },
        )

    raise SandboxConfigurationError(
        f"Sandbox backend {backend!r} is not wired yet; supported backend: unix_local"
    )


def _unix_local_run_config(sandbox_config: dict[str, Any]):
    from agents.run_config import SandboxArchiveLimits, SandboxConcurrencyLimits, SandboxRunConfig
    from agents.sandbox import Manifest
    from agents.sandbox.sandboxes.unix_local import UnixLocalSandboxClient

    manifest_payload = sandbox_config.get("manifest")
    if isinstance(manifest_payload, dict):
        manifest = Manifest.model_validate(manifest_payload)
    else:
        manifest = Manifest(root=str(sandbox_config.get("root") or "/workspace"))

    concurrency_payload = sandbox_config.get("concurrency_limits")
    if isinstance(concurrency_payload, dict):
        concurrency_limits = SandboxConcurrencyLimits(
            manifest_entries=concurrency_payload.get("manifest_entries"),
            local_dir_files=concurrency_payload.get("local_dir_files"),
        )
    else:
        concurrency_limits = SandboxConcurrencyLimits()

    archive_limits = None
    archive_payload = sandbox_config.get("archive_limits")
    if isinstance(archive_payload, dict):
        archive_limits = SandboxArchiveLimits(
            max_input_bytes=archive_payload.get("max_input_bytes"),
            max_extracted_bytes=archive_payload.get("max_extracted_bytes"),
            max_members=archive_payload.get("max_members"),
        )

    return SandboxRunConfig(
        client=UnixLocalSandboxClient(),
        manifest=manifest,
        concurrency_limits=concurrency_limits,
        archive_limits=archive_limits,
    )


def _default_backend_for_env(env_type: str) -> str:
    if env_type == "local":
        return "unix_local"
    if env_type == "self_hosted":
        return "self_hosted_worker"
    return "unconfigured_cloud"


def _environment_policy_summary(config: dict[str, Any]) -> dict[str, Any]:
    networking = dict(config.get("networking") or {"type": "unrestricted"})
    networking_type = networking.get("type") or "unrestricted"
    if networking_type in {"restricted", "none"}:
        networking_type = "limited"
    networking_summary = {
        "type": networking_type,
        "allowed_hosts": list(networking.get("allowed_hosts") or []),
        "allow_mcp_servers": bool(networking.get("allow_mcp_servers", False)),
        "allow_package_managers": bool(networking.get("allow_package_managers", False)),
    }
    if networking_summary["type"] == "unrestricted":
        networking_summary["allowed_hosts"] = []

    packages = dict(config.get("packages") or {})
    package_summary = {
        "apt": list(packages.get("apt") or []),
        "cargo": list(packages.get("cargo") or []),
        "gem": list(packages.get("gem") or []),
        "go": list(packages.get("go") or []),
        "npm": list(packages.get("npm") or []),
        "pip": list(packages.get("pip") or []),
    }

    resources = dict(config.get("resources") or {})
    resource_summary = {
        key: resources[key]
        for key in ("cpu", "memory_mb", "disk_mb", "timeout_seconds")
        if resources.get(key) is not None
    }

    return {
        "networking": networking_summary,
        "packages": package_summary,
        "resources": resource_summary,
    }
