"""Parse Kubernetes manifests into StackService records."""

from __future__ import annotations

from pathlib import Path

import yaml

from app.core.git.git_source_analysis import sanitize_container_name
from app.db.models import StackService

SUPPORTED_WORKLOAD_KINDS = {"Deployment", "StatefulSet"}


def parse_k8s(yaml_content: str) -> tuple[list[StackService], list[str]]:
    """Parse Kubernetes manifest YAML (multi-document) into StackService records.

    Returns:
        Tuple of (services, warnings). Warnings describe unsupported features
        that were dropped. Returns empty services when no workload resources exist.
    """
    try:
        documents = [
            document
            for document in yaml.safe_load_all(yaml_content)
            if isinstance(document, dict)
        ]
    except yaml.YAMLError:
        return [], ["Invalid YAML: could not parse the manifest."]

    warnings: list[str] = []
    config_maps: dict[str, dict[str, str]] = {}
    ingress_backend_names: set[str] = set()
    service_kind_names: list[str] = []
    workloads: list[tuple[StackService, list[str]]] = []

    for document in documents:
        kind = document.get("kind")
        if kind in SUPPORTED_WORKLOAD_KINDS:
            service, config_map_refs = _parse_workload(document, warnings)
            workloads.append((service, config_map_refs))
        elif kind == "ConfigMap":
            name = _doc_name(document)
            data = document.get("data")
            if name and isinstance(data, dict):
                config_maps[name] = {str(k): str(v) for k, v in data.items()}
        elif kind == "Ingress":
            ingress_backend_names |= _ingress_backend_service_names(document)
        elif kind == "Service":
            name = _doc_name(document)
            if name:
                service_kind_names.append(name)
        elif kind == "Secret":
            name = _doc_name(document)
            warnings.append(
                f"Secret '{name or 'unnamed'}' skipped — secrets cannot be "
                "imported. Add env vars manually."
            )
        elif kind == "PersistentVolumeClaim":
            warnings.append(
                f"PersistentVolumeClaim '{_doc_name(document) or 'unnamed'}' "
                "skipped — add volumes manually."
            )

    for service, config_map_refs in workloads:
        for config_map_name in config_map_refs:
            if config_map_name in config_maps:
                service.env_vars = {**config_maps[config_map_name], **service.env_vars}
            else:
                warnings.append(
                    f"Service '{service.service_name}': ConfigMap "
                    f"'{config_map_name}' not found in the manifest."
                )
        if service.service_name in ingress_backend_names:
            service.public_route = True

    workload_names = {service.service_name for service, _ in workloads}
    for orphan_name in service_kind_names:
        if orphan_name not in workload_names:
            warnings.append(
                f"Kubernetes Service '{orphan_name}' has no matching "
                "Deployment/StatefulSet and was ignored."
            )

    services = _deduplicate_names([service for service, _ in workloads])
    return services, warnings


def _file_has_workload_kind(path: Path) -> bool:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        for document in yaml.safe_load_all(text):
            if (
                isinstance(document, dict)
                and document.get("kind") in SUPPORTED_WORKLOAD_KINDS
                and isinstance(document.get("apiVersion"), str)
            ):
                return True
    except (OSError, yaml.YAMLError):
        return False
    return False


def _doc_name(document: dict) -> str:
    metadata = document.get("metadata")
    if isinstance(metadata, dict):
        return str(metadata.get("name") or "")
    return ""


def _parse_workload(
    document: dict,
    warnings: list[str],
) -> tuple[StackService, list[str]]:
    raw_name = _doc_name(document)
    name = sanitize_container_name(raw_name) or "service"

    spec = document.get("spec") or {}
    template_spec = (spec.get("template") or {}).get("spec") or {}
    containers = template_spec.get("containers") or []
    container = containers[0] if containers else {}

    image = str(container.get("image") or "").strip()
    if not image:
        warnings.append(
            f"Workload '{raw_name}': no container image, defaulting to 'nginx:alpine'."
        )
        image = "nginx:alpine"

    container_port = 80
    ports = container.get("ports")
    if isinstance(ports, list) and ports and isinstance(ports[0], dict):
        try:
            container_port = int(ports[0].get("containerPort"))
        except (TypeError, ValueError):
            pass

    env_vars: dict[str, str] = {}
    for entry in container.get("env") or []:
        if not isinstance(entry, dict):
            continue
        key = str(entry.get("name") or "").strip()
        if not key:
            continue
        value = entry.get("value")
        env_vars[key] = "" if value is None else str(value)

    config_map_refs: list[str] = []
    for source in container.get("envFrom") or []:
        if not isinstance(source, dict):
            continue
        config_map_ref = source.get("configMapRef")
        if isinstance(config_map_ref, dict):
            ref_name = str(config_map_ref.get("name") or "")
            if ref_name:
                config_map_refs.append(ref_name)
            continue
        secret_ref = source.get("secretRef")
        if isinstance(secret_ref, dict):
            warnings.append(
                f"Service '{name}': secretRef "
                f"'{secret_ref.get('name') or 'unnamed'}' skipped — "
                "add env vars manually."
            )

    tokens: list[str] | None = None
    command = container.get("command")
    args = container.get("args")
    combined = [str(token) for token in (command or []) + (args or [])]
    if combined:
        tokens = combined

    if container.get("volumeMounts"):
        warnings.append(
            f"Service '{name}': volumeMounts skipped — add volumes manually."
        )

    service = StackService(
        service_name=name,
        source_kind="image",
        source_ref=image,
        git_branch=None,
        container_port=container_port,
        env_vars=env_vars,
        command=tokens,
        public_route=False,
        depends_on=None,
    )
    return service, config_map_refs


def _ingress_backend_service_names(document: dict) -> set[str]:
    names: set[str] = set()
    rules = (document.get("spec") or {}).get("rules") or []
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        paths = ((rule.get("http") or {}).get("paths")) or []
        for path_entry in paths:
            if not isinstance(path_entry, dict):
                continue
            backend = path_entry.get("backend") or {}
            backend_service = backend.get("service")
            if isinstance(backend_service, dict):
                name = str(backend_service.get("name") or "")
                if name:
                    names.add(sanitize_container_name(name) or name)
    return names


def _deduplicate_names(services: list[StackService]) -> list[StackService]:
    seen: set[str] = set()
    result: list[StackService] = []
    for service in services:
        name = service.service_name
        if name in seen:
            suffix = 2
            while f"{name}-{suffix}" in seen:
                suffix += 1
            name = f"{name}-{suffix}"
            service.service_name = name
        seen.add(name)
        result.append(service)
    return result
