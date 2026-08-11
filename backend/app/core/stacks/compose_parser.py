"""Parse docker-compose YAML into StackService records."""

from __future__ import annotations

import yaml

from app.db.models import StackService


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
            container_port=container_port,
            env_vars=env_vars,
            command=command,
            public_route=False,
            depends_on=depends_on if depends_on else None,
        ),
        warnings,
    )


def _resolve_source(
    config: dict,
    name: str,
    warnings: list[str],
) -> tuple[str, str]:
    """Determine source_kind and source_ref from image or build config."""
    image = config.get("image")
    if image:
        return "image", str(image)

    build = config.get("build")
    if isinstance(build, str):
        return "dockerfile_template", build
    if isinstance(build, dict):
        context = build.get("context", ".")
        return "dockerfile_template", str(context)

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
        return {str(k): str(v) if v is not None else "" for k, v in env.items()}
    if isinstance(env, list):
        result = {}
        for item in env:
            item_str = str(item)
            if "=" in item_str:
                key, _, value = item_str.partition("=")
                result[key] = value
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
