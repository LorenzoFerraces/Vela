"""Parse docker-compose YAML into StackService records."""

from __future__ import annotations

import re

import yaml

from app.db.models import StackService

# ${VAR:-default} or ${VAR-default} — capture default when host env is unavailable.
_BRACE_DEFAULT_PATTERN = re.compile(
    r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?:(:-|-)([^}]*))?\}"
)
# Bare $VAR (not preceded by another $).
_SIMPLE_VAR_PATTERN = re.compile(r"(?<!\$)\$([A-Za-z_][A-Za-z0-9_]*)")


def resolve_compose_interpolation(value: str) -> str:
    """Resolve Compose/shell-style env interpolation for import into Vela.

    Host environment is not available during import, so:
    - ``${VAR:-default}`` / ``${VAR-default}`` → ``default``
    - ``${VAR}`` / ``$VAR`` → empty string
    """

    def replace_braced(match: re.Match[str]) -> str:
        default = match.group(3)
        if default is not None:
            return default
        return ""

    resolved = _BRACE_DEFAULT_PATTERN.sub(replace_braced, value)
    return _SIMPLE_VAR_PATTERN.sub("", resolved)


def parse_compose(yaml_content: str) -> tuple[list[StackService], list[str]]:
    """Parse docker-compose YAML content into StackService records.

    Returns:
        Tuple of (services, warnings). Warnings describe unsupported features
        that were dropped. The service is still created without the unsupported feature.
    """
    data = yaml.safe_load(yaml_content)
    if not isinstance(data, dict):
        return [], ["Invalid compose file: expected a mapping at the top level."]

    services_config = data.get("services", {})
    if not isinstance(services_config, dict):
        return [], []

    warnings: list[str] = []
    services: list[StackService] = []

    for service_name, config in services_config.items():
        if not isinstance(config, dict):
            warnings.append(f"Service '{service_name}': invalid configuration, skipping.")
            continue

        service, service_warnings = _parse_service(service_name, config)
        services.append(service)
        warnings.extend(service_warnings)

    return services, warnings


def _parse_service(
    name: str,
    config: dict,
) -> tuple[StackService, list[str]]:
    """Parse a single service configuration into a StackService."""
    warnings: list[str] = []

    source_kind, source_ref = _resolve_source(config, name, warnings)
    git_branch = "main" if source_kind == "git" else None
    container_port = _extract_container_port(config, warnings)
    env_vars = _extract_env(config)

    command = config.get("command")
    if isinstance(command, str):
        command = command.split()
    elif not isinstance(command, list):
        command = None

    depends_on = _extract_depends_on(config)
    _check_unsupported(config, name, warnings)

    return (
        StackService(
            service_name=name,
            source_kind=source_kind,
            source_ref=source_ref,
            git_branch=git_branch,
            container_port=container_port,
            env_vars=env_vars,
            command=command,
            public_route=False,
            depends_on=depends_on if depends_on else None,
        ),
        warnings,
    )


def _looks_like_git_url(value: str) -> bool:
    stripped = value.strip()
    return (
        stripped.startswith("git@")
        or stripped.startswith("http://")
        or stripped.startswith("https://")
        or stripped.startswith("ssh://")
    )


def _resolve_source(
    config: dict,
    name: str,
    warnings: list[str],
) -> tuple[str, str]:
    """Determine source_kind and source_ref from image or build config."""
    image = config.get("image")
    if image:
        image_ref = str(image).strip()
        if _looks_like_git_url(image_ref):
            warnings.append(
                f"Service '{name}': image looks like a git URL — treating as git source."
            )
            return "git", image_ref
        return "image", image_ref

    build = config.get("build")
    if isinstance(build, str):
        build_ref = build.strip()
        if _looks_like_git_url(build_ref):
            return "git", build_ref
        return "dockerfile_template", build_ref
    if isinstance(build, dict):
        context = str(build.get("context", ".")).strip()
        if _looks_like_git_url(context):
            return "git", context
        return "dockerfile_template", context

    warnings.append(f"Service '{name}': no image or build specified, defaulting to 'nginx:alpine'.")
    return "image", "nginx:alpine"


def _extract_container_port(config: dict, warnings: list[str]) -> int:
    """Extract the container port from ports mapping or expose."""
    _ = warnings
    ports = config.get("ports", [])
    if isinstance(ports, list) and ports:
        first_port = str(ports[0])
        if ":" in first_port:
            parts = first_port.rsplit(":", 1)
            try:
                return int(parts[1].split("/")[0])
            except (ValueError, IndexError):
                pass
        try:
            return int(first_port.split("/")[0])
        except ValueError:
            pass

    expose = config.get("expose", [])
    if isinstance(expose, list) and expose:
        try:
            return int(str(expose[0]))
        except ValueError:
            pass

    return 80


def _extract_env(config: dict) -> dict[str, str]:
    """Extract environment variables from list or dict format."""
    env = config.get("environment", {})
    if isinstance(env, dict):
        return {
            str(key): resolve_compose_interpolation(str(value) if value is not None else "")
            for key, value in env.items()
        }
    if isinstance(env, list):
        result: dict[str, str] = {}
        for item in env:
            item_str = str(item)
            if "=" in item_str:
                key, _, value = item_str.partition("=")
                result[key] = resolve_compose_interpolation(value)
            else:
                result[item_str] = ""
        return result
    return {}


def _extract_depends_on(config: dict) -> list[str] | None:
    """Extract depends_on as a list of service names."""
    depends = config.get("depends_on")
    if isinstance(depends, list):
        return [str(d) for d in depends]
    if isinstance(depends, dict):
        return list(depends.keys())
    return None


def _check_unsupported(config: dict, name: str, warnings: list[str]) -> None:
    """Check for unsupported compose features and emit warnings."""
    unsupported = {
        "volumes": "volume mounts",
        "secrets": "secrets",
        "configs": "configs",
        "deploy": "deploy resources (CPU/memory limits, replicas)",
        "healthcheck": "health checks",
        "extends": "extends",
        "networks": "custom networks (Vela uses a shared stack network)",
    }

    for key, label in unsupported.items():
        if key in config:
            warnings.append(
                f"Service '{name}': unsupported feature '{key}' ({label}) — "
                f"service will be created without this feature."
            )
