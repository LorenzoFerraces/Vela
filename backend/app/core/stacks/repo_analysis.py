from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml
from pydantic import ValidationError

from app.api.schemas import StackServiceCreate
from app.core.build.default_image_builder import DefaultImageBuilder
from app.core.exceptions import LlmCallError, ManifestParseError
from app.core.git.git_ops import head_commit, rm_tree
from app.core.git.git_source_analysis import (
    _collect_context_excerpts,
    _detected_facts_block,
    _env_vars_from_payload,
    _extract_env_vars_from_context,
    _read_file_excerpt,
)
from app.core.llm import generate_json
from app.core.llm.cache import load_cached, store_cached
from app.core.stacks.k8s_parser import _file_has_workload_kind
from app.core.stacks.manifest_parser import parse_manifest
from app.db.models import StackService
from app.e2e_support import e2e_stack_repo_analysis_if_enabled

ManifestKind = Literal["compose", "k8s"]
RepoAnalysisKind = Literal["compose", "k8s", "llm"]
_IGNORED_DIRECTORIES = frozenset(
    {".git", "node_modules", "vendor", "__pycache__", ".venv", "venv", "dist", "build"}
)
_COMPOSE_NAMES = ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml")
_COMPOSE_PATTERNS = ("docker-compose", "compose")
_PREFERRED_DIRECTORIES = ("k8s", "kubernetes", "deploy", "manifests")
STACKS_PROMPT_VERSION = "v2"  # ponytail: bump when the stacks prompt text changes


@dataclass(frozen=True)
class RepoStackAnalysis:
    services: list[StackService]
    warnings: list[str]
    manifest_kind: RepoAnalysisKind
    manifest_path: str | None
    summary_hint: str | None


def _is_ignored(path: Path) -> bool:
    return any(part in _IGNORED_DIRECTORIES or part.startswith(".") for part in path.parts)


def _yaml_files(root: Path) -> list[Path]:
    return sorted(
        (
            path
            for path in root.rglob("*")
            if path.is_file() and path.suffix.lower() in {".yml", ".yaml"} and not _is_ignored(path.relative_to(root))
        ),
        key=lambda path: str(path.relative_to(root)),
    )


def _is_compose_file(path: Path) -> bool:
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, yaml.YAMLError):
        return False
    return (
        isinstance(document, dict)
        and isinstance(document.get("services"), dict)
    )


def _classify_yaml_file(path: Path) -> ManifestKind | None:
    if _is_compose_file(path):
        return "compose"
    if _file_has_workload_kind(path):
        return "k8s"
    return None


def _immediate_compose_files(root: Path) -> list[Path]:
    directories = sorted(
        (
            path
            for path in root.iterdir()
            if path.is_dir()
            and not path.name.startswith(".")
            and path.name not in _IGNORED_DIRECTORIES
        ),
        key=lambda path: path.name,
    )
    return sorted(
        (
            path
            for directory in directories
            for path in directory.iterdir()
            if path.is_file()
            and path.suffix.lower() in {".yml", ".yaml"}
            and any(path.stem.startswith(prefix) for prefix in _COMPOSE_PATTERNS)
        ),
        key=lambda path: str(path.relative_to(root)),
    )


def detect_manifest_file(root: Path) -> tuple[Path, ManifestKind] | None:
    for name in _COMPOSE_NAMES:
        path = root / name
        if path.is_file() and _is_compose_file(path):
            return path, "compose"

    for path in _immediate_compose_files(root):
        if _is_compose_file(path):
            return path, "compose"

    deferred_k8s: tuple[Path, ManifestKind] | None = None
    searched: set[Path] = set()
    for directory_name in _PREFERRED_DIRECTORIES:
        directory = root / directory_name
        if not directory.is_dir() or directory.name.startswith("."):
            continue
        for path in _yaml_files(directory):
            searched.add(path)
            kind = _classify_yaml_file(path)
            if kind == "compose":
                return path, kind
            if kind == "k8s" and deferred_k8s is None:
                deferred_k8s = (path, kind)

    other_files = [path for path in _yaml_files(root) if path not in searched]
    for path in other_files:
        kind = _classify_yaml_file(path)
        if kind == "compose":
            return path, kind
        if kind == "k8s" and deferred_k8s is None:
            deferred_k8s = (path, kind)
    return deferred_k8s


def _generation_schema() -> dict:
    return {
        "type": "OBJECT",
        "properties": {
            "services": {
                "type": "ARRAY",
                "items": {
                    "type": "OBJECT",
                    "properties": {
                        "service_name": {"type": "STRING"},
                        "source_kind": {"type": "STRING", "enum": ["git", "image"]},
                        "source_ref": {"type": "STRING"},
                        "container_port": {"type": "INTEGER"},
                        "env_var_entries": {
                            "type": "ARRAY",
                            "items": {
                                "type": "OBJECT",
                                "properties": {
                                    "key": {"type": "STRING"},
                                    "value": {"type": "STRING"},
                                },
                                "required": ["key", "value"],
                            },
                        },
                        "command": {
                            "type": "ARRAY",
                            "nullable": True,
                            "items": {"type": "STRING"},
                        },
                        "public_route": {"type": "BOOLEAN"},
                        "depends_on": {
                            "type": "ARRAY",
                            "nullable": True,
                            "items": {"type": "STRING"},
                        },
                    },
                    "required": [
                        "service_name",
                        "source_kind",
                        "source_ref",
                        "container_port",
                        "env_var_entries",
                        "command",
                        "public_route",
                        "depends_on",
                    ],
                },
            },
            "summary_hint": {"type": "STRING"},
        },
        "required": ["services", "summary_hint"],
    }


def _payload_to_services(
    payload: dict[str, object],
    *,
    git_url: str,
    git_branch: str,
    warnings: list[str],
    env_fallback: dict[str, str] | None = None,
) -> list[StackService]:
    raw_services = payload.get("services")
    if not isinstance(raw_services, list):
        raise LlmCallError("AI analysis returned no usable services.")

    services: list[StackService] = []
    for raw_service in raw_services:
        if not isinstance(raw_service, dict):
            warnings.append("AI analysis returned an invalid service, which was skipped.")
            continue
        name = raw_service.get("service_name")
        source_kind = raw_service.get("source_kind")
        source_ref = raw_service.get("source_ref")
        if not isinstance(name, str) or not name.strip():
            warnings.append("AI analysis returned a service with no name, which was skipped.")
            continue
        if source_kind not in {"git", "image"}:
            warnings.append(
                f"Service '{name.strip()}': unsupported source kind, which was skipped."
            )
            continue
        if not isinstance(source_ref, str):
            source_ref = ""
        source_ref = source_ref.strip()
        if source_kind == "git" and not source_ref:
            source_ref = git_url.strip()
        if not source_ref:
            warnings.append(
                f"Service '{name.strip()}': source reference is empty, which was skipped."
            )
            continue

        raw_port = raw_service.get("container_port")
        port = raw_port if isinstance(raw_port, int) and not isinstance(raw_port, bool) else 80
        if not 1 <= port <= 65535:
            port = 80
        env_vars = _env_vars_from_payload(raw_service)
        if source_kind == "git" and env_fallback:
            env_vars = {**env_fallback, **env_vars}
        data = {
            "service_name": name.strip(),
            "source_kind": source_kind,
            "source_ref": source_ref,
            "git_branch": git_branch if source_kind == "git" else None,
            "container_port": port,
            "env_vars": env_vars,
            "command": raw_service.get("command"),
            "public_route": raw_service.get("public_route", False),
            "depends_on": raw_service.get("depends_on"),
        }
        try:
            service_data = StackServiceCreate.model_validate(data)
        except (TypeError, ValidationError):
            warnings.append(
                f"Service '{name.strip()}': invalid generated configuration, which was skipped."
            )
            continue
        services.append(
            StackService(
                service_name=service_data.service_name,
                source_kind=service_data.source_kind,
                source_ref=service_data.source_ref,
                git_branch=service_data.git_branch,
                container_port=service_data.container_port,
                env_vars=service_data.env_vars,
                command=service_data.command,
                public_route=service_data.public_route,
                depends_on=service_data.depends_on,
                volumes=[],
            )
        )

    if not services:
        raise LlmCallError("AI analysis returned no usable services.")
    return services


async def _generate_services(
    *,
    context: str,
    manifest: str | None,
    git_url: str,
    git_branch: str,
    warnings: list[str],
    root: Path,
    commit: str = "",
) -> tuple[list[StackService], str | None]:
    prompt = (
        "Analyze this repository and produce the deployable services for a Vela stack. "
        "Every repository-built service must use source_kind: \"git\" and use the supplied "
        "repository URL as source_ref. External dependencies such as databases, caches, and "
        "queues must use source_kind: \"image\" and an image reference as source_ref. "
        "Populate env_var_entries with every environment variable named in README tables, "
        ".env.example files, or export lines; use documented example values when present, "
        "otherwise an empty string. "
        "When Detected facts are supplied, treat them as ground truth for ports and "
        "environment variables. "
        "Do not use host paths, volume sources, or unsupported source kinds. "
        "Use an empty source_ref only when source_kind is git and the supplied repository URL "
        "will be used. Return only JSON matching the schema.\n\n"
        f"Repository URL: {git_url}\nRequested branch: {git_branch}\n\n"
        f"Repository context:\n{context}"
    )
    if manifest:
        prompt += f"\n\nDeployment manifest excerpt:\n{manifest}"
    facts = _detected_facts_block(root, context)
    if facts:
        prompt += (
            "\n\nDetected facts (already verified by deterministic scans; "
            f"prefer them over re-deriving):\n{facts}"
        )
    payload = load_cached("stacks", commit, STACKS_PROMPT_VERSION)
    if payload is None:
        payload = await generate_json(prompt=prompt, schema=_generation_schema())
        store_cached("stacks", commit, STACKS_PROMPT_VERSION, payload)
    services = _payload_to_services(
        payload,
        git_url=git_url,
        git_branch=git_branch,
        warnings=warnings,
        env_fallback=_extract_env_vars_from_context(context),
    )
    summary = payload.get("summary_hint")
    return services, summary.strip() if isinstance(summary, str) and summary.strip() else None


async def analyze_repo_stack(
    image_builder: DefaultImageBuilder,
    *,
    git_url: str,
    git_branch: str,
    access_token: str | None,
) -> RepoStackAnalysis:
    fixture = e2e_stack_repo_analysis_if_enabled(git_url, git_branch)
    if fixture is not None:
        return fixture

    project_path = await image_builder.clone_repository(
        git_url,
        branch=git_branch,
        access_token=access_token,
    )
    root = Path(project_path)
    commit = head_commit(root) or ""
    parent = root.parent
    try:
        detected = detect_manifest_file(root)
        warnings: list[str] = []
        manifest_content: str | None = None
        manifest_excerpt: str | None = None
        if detected is not None:
            manifest_path, manifest_kind = detected
            relative_path = manifest_path.relative_to(root).as_posix()
            warnings.append(f"Selected manifest '{relative_path}'.")
            manifest_content = manifest_path.read_text(encoding="utf-8", errors="replace")
            manifest_excerpt = _read_file_excerpt(manifest_path)
            try:
                services, parser_warnings, parsed_kind = parse_manifest(manifest_content)
            except ManifestParseError:
                if manifest_kind != "compose":
                    raise
                services, parser_warnings, parsed_kind = [], [], manifest_kind
            warnings.extend(parser_warnings)
            if services:
                return RepoStackAnalysis(
                    services=services,
                    warnings=warnings,
                    manifest_kind=parsed_kind,
                    manifest_path=relative_path,
                    summary_hint=None,
                )
            warnings.append("Selected manifest contained no usable services; using AI analysis.")
        else:
            relative_path = None

        services, summary_hint = await _generate_services(
            context=_collect_context_excerpts(root),
            manifest=manifest_excerpt,
            git_url=git_url,
            git_branch=git_branch,
            warnings=warnings,
            root=root,
            commit=commit,
        )
        return RepoStackAnalysis(
            services=services,
            warnings=warnings,
            manifest_kind="llm",
            manifest_path=relative_path,
            summary_hint=summary_hint,
        )
    finally:
        rm_tree(parent)
