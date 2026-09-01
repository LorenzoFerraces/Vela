"""Gemini-backed Git repository analysis for deploy form pre-fill."""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import ValidationError

from app.api.schemas import GitSourceAnalysis
from app.core.build.default_image_builder import DefaultImageBuilder
from app.core.enums import SupportedLanguage
from app.core.exceptions import (
    GitSourceAnalysisError,
    LlmCallError,
    LlmNotConfiguredError,
)
from app.core.git.git_ops import head_commit
from app.core.git.project_analysis import analyze_project
from app.core.llm import generate_json, resolve_llm_config
from app.core.llm.cache import delete_cached, load_cached, store_cached
from app.e2e_support import e2e_git_source_analysis_if_enabled
MAX_FILE_BYTES = 12_000
MAX_TOTAL_BYTES = 48_000
GIT_SOURCE_PROMPT_VERSION = "v1"  # ponytail: bump when the git-source prompt text changes

_README_CANDIDATES = ("README.md", "README", "readme.md", "Readme.md")

_OTHER_CONTEXT_FILES = (
    "package.json",
    "pyproject.toml",
    "requirements.txt",
    "go.mod",
)

_ENV_EXAMPLE_PATHS = (
    ".env.example",
    "env.example",
    "frontend/.env.example",
    "backend/.env.example",
)

_README_SECTION_KEYWORDS = (
    "env",
    "config",
    "deploy",
    "docker",
    "compose",
    "k8s",
    "port",
    "install",
    "setup",
    "run",
    "usage",
    "start",
    "requirement",
)

_MAP_IGNORED = frozenset(
    {
        ".git",
        "node_modules",
        "vendor",
        "__pycache__",
        ".venv",
        "venv",
        "dist",
        "build",
        "target",
        ".next",
        ".turbo",
        "coverage",
    }
)

_SUBDIR_MARKER_NAMES = (
    "Dockerfile",
    "package.json",
    "pyproject.toml",
    "requirements.txt",
    "go.mod",
    ".env.example",
)
_MAX_SUBDIR_FILES = 6

_ENV_VAR_TABLE_ROW = re.compile(
    r"^\|\s*`?([A-Za-z_][A-Za-z0-9_]*)`?\s*\|",
    re.MULTILINE,
)
_ENV_ASSIGNMENT = re.compile(
    r"^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$",
)

GIT_SOURCE_ANALYSIS_PROMPT_V1 = """You analyze Git repositories for deployment on Vela (Docker containers behind Traefik public routes).

Given repository file excerpts, infer how the app should be deployed. The README excerpt (when present) is the primary source for ports, environment variables, and run/setup commands. When a Detected facts block is supplied, treat it as ground truth for ports, environment variables, and build signals.
- container_port: TCP port the app listens on inside the container (e.g. 5173 for Vite, 8000 for FastAPI, 8080 for Go). Prefer values documented in the README.
- container_name: short DNS-safe name derived from the repo (lowercase, hyphens).
- git_branch: keep the requested branch unless excerpts clearly indicate another default.
- env_var_entries: array of {key, value} for every environment variable named in the README table, .env.example, or export KEY=value lines. Use documented example values when present; otherwise value may be "".
- start_command: optional CMD override tokens as a JSON array, or null to use the image default. Prefer README run/dev/docker commands when stated.
- language, framework: short labels or null.
- has_dockerfile: true if a Dockerfile exists in excerpts.
- build_strategy: "dockerfile_exists" if Dockerfile present, else "generated_dockerfile".
- summary_hint: one short sentence for the UI (max 120 chars).

Respond with JSON matching the schema exactly."""


def _read_file_excerpt(path: Path) -> str:
    raw = path.read_bytes()
    if len(raw) > MAX_FILE_BYTES:
        return raw[:MAX_FILE_BYTES].decode("utf-8", errors="replace") + "\n…"
    return raw.decode("utf-8", errors="replace")


def _find_readme(project_root: Path) -> Path | None:
    for name in _README_CANDIDATES:
        path = project_root / name
        if path.is_file():
            return path
    return None


def _select_readme_text(text: str) -> str:
    if len(text.encode("utf-8")) <= MAX_FILE_BYTES:
        return text
    return _extract_readme_sections(text) or text[:MAX_FILE_BYTES]


def _extract_readme_sections(text: str, max_bytes: int = 8_000) -> str:
    lines = text.splitlines()
    section_indices: list[int] = []
    env_indices: set[int] = set()
    in_kept_section = False
    for index, line in enumerate(lines):
        stripped = line.strip()
        if line.startswith("#"):
            in_kept_section = any(
                keyword in line.lower() for keyword in _README_SECTION_KEYWORDS
            )
            if in_kept_section:
                section_indices.append(index)
            continue
        if in_kept_section:
            section_indices.append(index)
        if _ENV_VAR_TABLE_ROW.match(line) or _ENV_ASSIGNMENT.match(stripped):
            for context_index in range(index - 2, index + 3):
                if 0 <= context_index < len(lines):
                    env_indices.add(context_index)
    section_text = "\n".join(lines[index] for index in section_indices)
    if len(section_text) < 800:
        section_indices = []
    keep = sorted(set(section_indices) | env_indices)
    if not keep:
        return ""
    kept_text = "\n".join(lines[index] for index in keep)
    if len(kept_text.encode("utf-8")) > max_bytes:
        kept_text = (
            kept_text.encode("utf-8", errors="replace")[:max_bytes].decode(
                "utf-8", errors="replace"
            )
            + "…"
        )
    return kept_text


def _repo_map(root: Path, max_entries: int = 150) -> str:
    entries: list[str] = []

    def walk(directory: Path) -> None:
        try:
            children = sorted(directory.iterdir(), key=lambda item: item.name)
        except OSError:
            return
        for child in children:
            if child.name.startswith(".") or child.name in _MAP_IGNORED:
                continue
            if child.is_symlink():
                continue
            if child.is_dir():
                walk(child)
            else:
                entries.append(child.relative_to(root).as_posix())

    walk(root)
    entries.sort()
    if len(entries) > max_entries:
        entries = entries[:max_entries] + ["…"]
    return "\n".join(entries)


def _subdir_marker_files(root: Path) -> list[tuple[str, str]]:
    for name in _SUBDIR_MARKER_NAMES:
        if (root / name).is_file():
            return []
    results: list[tuple[str, str]] = []
    try:
        children = sorted(root.iterdir(), key=lambda item: item.name)
    except OSError:
        return []
    for child in children:
        if not child.is_dir() or child.name.startswith(".") or child.name in _MAP_IGNORED:
            continue
        markers = sorted(
            (child / name) for name in _SUBDIR_MARKER_NAMES if (child / name).is_file()
        )
        for marker in markers:
            if len(results) >= _MAX_SUBDIR_FILES:
                break
            results.append((f"{child.name}/{marker.name}", _read_file_excerpt(marker)))
        if len(results) >= _MAX_SUBDIR_FILES:
            break
    return results


def _append_excerpt(
    parts: list[str],
    *,
    total: int,
    label: str,
    text: str,
) -> int:
    chunk = f"=== {label} ===\n{text.strip()}\n"
    if total + len(chunk) > MAX_TOTAL_BYTES:
        return total
    parts.append(chunk)
    return total + len(chunk)


def _collect_context_excerpts(project_root: Path) -> str:
    parts: list[str] = []
    total = 0

    for relative_path in _ENV_EXAMPLE_PATHS:
        path = project_root / relative_path
        if not path.is_file():
            continue
        total = _append_excerpt(
            parts,
            total=total,
            label=relative_path,
            text=_read_file_excerpt(path),
        )

    dockerfile_path = project_root / "Dockerfile"
    if dockerfile_path.is_file():
        total = _append_excerpt(
            parts,
            total=total,
            label="Dockerfile",
            text=_read_file_excerpt(dockerfile_path),
        )

    for name in _OTHER_CONTEXT_FILES:
        path = project_root / name
        if not path.is_file():
            continue
        total = _append_excerpt(
            parts,
            total=total,
            label=name,
            text=_read_file_excerpt(path),
        )

    readme_path = _find_readme(project_root)
    if readme_path is not None:
        readme_text = readme_path.read_bytes().decode("utf-8", errors="replace")
        total = _append_excerpt(
            parts,
            total=total,
            label=readme_path.name,
            text=_select_readme_text(readme_text),
        )

    for label, text in _subdir_marker_files(project_root):
        total = _append_excerpt(parts, total=total, label=label, text=text)

    map_text = _repo_map(project_root)
    if map_text:
        total = _append_excerpt(
            parts,
            total=total,
            label="repo map",
            text=map_text,
        )

    if not parts:
        info = analyze_project(project_root)
        parts.append(
            f"=== analysis ===\nlanguage={info.language}\n"
            f"has_dockerfile={info.has_dockerfile}\n"
            f"dependency_file={info.dependency_file}\n"
        )
    return "\n".join(parts)


def _table_row_env_value(line: str, key: str) -> str:
    """Pull an example value from a markdown table notes column, if any."""
    cells = [cell.strip() for cell in line.split("|")]
    if len(cells) < 3:
        return ""
    notes = cells[2]
    for candidate in re.findall(r"`([^`]+)`", notes):
        if candidate == key:
            continue
        if "=" in candidate or "://" in candidate or candidate.isdigit():
            return candidate
    return ""


def _extract_env_vars_from_context(context: str) -> dict[str, str]:
    """Deterministic env pre-fill from README tables and .env.example excerpts."""
    env_vars: dict[str, str] = {}
    for line in context.splitlines():
        table_match = _ENV_VAR_TABLE_ROW.match(line)
        if table_match:
            key = table_match.group(1)
            if key.lower() in {"variable", "notes"}:
                continue
            env_vars[key] = _table_row_env_value(line, key)
            continue
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        assign_match = _ENV_ASSIGNMENT.match(stripped)
        if assign_match:
            key = assign_match.group(1).strip()
            value = assign_match.group(2).strip().strip('"').strip("'")
            if key:
                env_vars[key] = value
    return env_vars


def _dockerfile_facts(text: str) -> str | None:
    base: str | None = None
    ports: list[str] = []
    command: str | None = None
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        tokens = stripped.split()
        instruction = tokens[0].upper()
        if instruction == "FROM":
            for token in tokens[1:]:
                if not token.startswith("--"):
                    base = token
                    break
        elif instruction == "EXPOSE":
            for token in tokens[1:]:
                port = token.split("/")[0]
                if port.isdigit() and port not in ports:
                    ports.append(port)
        elif instruction in {"CMD", "ENTRYPOINT"}:
            command = stripped[:120]
    if base is None and not ports and command is None:
        return None
    facts: list[str] = []
    if base is not None:
        facts.append(f"base={base}")
    if ports:
        facts.append(f"expose={','.join(ports)}")
    if command is not None:
        facts.append(f"cmd={command}")
    return " ".join(facts)


def _detected_facts_block(root: Path, context: str) -> str:
    lines: list[str] = []
    info = analyze_project(root)
    if info.language is not SupportedLanguage.UNKNOWN:
        language_line = f"language={info.language}"
        if info.framework:
            language_line += f", framework={info.framework}"
        lines.append(language_line)
    if info.build_subdir:
        lines.append(f"app markers live in '{info.build_subdir}/'")
    dockerfile_path = root / "Dockerfile"
    if dockerfile_path.is_file():
        dockerfile_facts = _dockerfile_facts(_read_file_excerpt(dockerfile_path))
        if dockerfile_facts is not None:
            lines.append(f"dockerfile: {dockerfile_facts}")
    env_vars = _extract_env_vars_from_context(context)
    if env_vars:
        rendered = ", ".join(
            f"{key}={value}" if value else key
            for key, value in list(env_vars.items())[:20]
        )
        if len(env_vars) > 20:
            rendered += " (more truncated)"
        lines.append(f"documented env vars: {rendered}")
    return "\n".join(f"- {line}" for line in lines)


def _env_vars_from_payload(parsed: dict[str, object]) -> dict[str, str]:
    """Gemini may return ``env_var_entries``; older payloads may use ``env_vars`` object."""
    env_vars: dict[str, str] = {}
    legacy = parsed.get("env_vars")
    if isinstance(legacy, dict):
        for key, value in legacy.items():
            if isinstance(key, str) and key.strip():
                env_vars[key.strip()] = "" if value is None else str(value)
    entries = parsed.get("env_var_entries")
    if isinstance(entries, list):
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            key = str(entry.get("key") or "").strip()
            if not key:
                continue
            raw_value = entry.get("value")
            env_vars[key] = "" if raw_value is None else str(raw_value)
    return env_vars


def _payload_to_analysis(parsed: dict[str, object]) -> GitSourceAnalysis:
    env_vars = _env_vars_from_payload(parsed)
    payload = dict(parsed)
    payload["env_vars"] = env_vars
    payload.pop("env_var_entries", None)
    return GitSourceAnalysis.model_validate(payload)


def _merge_env_fallback(
    analysis: GitSourceAnalysis,
    context: str,
) -> GitSourceAnalysis:
    if analysis.env_vars:
        return analysis
    extracted = _extract_env_vars_from_context(context)
    if not extracted:
        return analysis
    return analysis.model_copy(update={"env_vars": extracted})


def _enrich_with_local_detection(
    analysis: GitSourceAnalysis,
    project_root: Path,
) -> GitSourceAnalysis:
    info = analyze_project(project_root)
    needs_manual = (
        not info.has_dockerfile and info.language is SupportedLanguage.UNKNOWN
    )
    return analysis.model_copy(
        update={
            "build_subdir": info.build_subdir,
            "needs_manual_build_config": needs_manual,
        }
    )


def _analysis_json_schema() -> dict:
    """Gemini ``responseSchema`` subset (UPPERCASE types, ``nullable``, no type arrays)."""
    return {
        "type": "OBJECT",
        "properties": {
            "git_branch": {"type": "STRING", "nullable": True},
            "container_port": {"type": "INTEGER"},
            "container_name": {"type": "STRING", "nullable": True},
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
            "start_command": {
                "type": "ARRAY",
                "nullable": True,
                "items": {"type": "STRING"},
            },
            "language": {"type": "STRING", "nullable": True},
            "framework": {"type": "STRING", "nullable": True},
            "has_dockerfile": {"type": "BOOLEAN"},
            "build_strategy": {
                "type": "STRING",
                "enum": ["dockerfile_exists", "generated_dockerfile"],
            },
            "summary_hint": {"type": "STRING"},
        },
        "required": [
            "git_branch",
            "container_port",
            "container_name",
            "env_var_entries",
            "start_command",
            "language",
            "framework",
            "has_dockerfile",
            "build_strategy",
            "summary_hint",
        ],
    }


async def _call_gemini(
    context: str,
    git_url: str,
    git_branch: str,
    facts: str = "",
    commit: str = "",
) -> GitSourceAnalysis:
    prompt = (
        f"{GIT_SOURCE_ANALYSIS_PROMPT_V1}\n\n"
        f"Repository: {git_url}\n"
        f"Requested branch: {git_branch}\n\n"
        f"{context}"
    )
    if facts:
        prompt += (
            "\n\nDetected facts (already verified by deterministic scans; "
            f"prefer them over re-deriving):\n{facts}"
        )
    cache_key = f"{commit}:{git_branch}" if commit else ""
    try:
        parsed = load_cached("git_source", cache_key, GIT_SOURCE_PROMPT_VERSION)
        if parsed is None:
            parsed = await generate_json(prompt=prompt, schema=_analysis_json_schema())
            store_cached("git_source", cache_key, GIT_SOURCE_PROMPT_VERSION, parsed)
    except LlmNotConfiguredError as exc:
        raise GitSourceAnalysisError("AI analysis is not configured on this server.") from exc
    except LlmCallError as exc:
        if str(exc) == "Could not complete AI analysis. Try again later.":
            raise GitSourceAnalysisError(
                "Could not complete AI repository analysis. Try again later."
            ) from exc
        raise GitSourceAnalysisError(
            "AI analysis returned an invalid response. Try again or fill the form manually."
        ) from exc

    try:
        analysis = _payload_to_analysis(parsed)
        sanitized_name = sanitize_container_name(analysis.container_name)
        if sanitized_name != analysis.container_name:
            return analysis.model_copy(update={"container_name": sanitized_name})
        return analysis
    except (TypeError, ValidationError) as exc:
        delete_cached("git_source", cache_key, GIT_SOURCE_PROMPT_VERSION)
        raise GitSourceAnalysisError(
            "AI analysis returned an invalid response. Try again or fill the form manually."
        ) from exc


def _fallback_analysis(project_root: Path, git_branch: str) -> GitSourceAnalysis:
    info = analyze_project(project_root)
    port = 80
    if info.language in {"typescript", "javascript"}:
        port = 5173
    elif info.language == "python":
        port = 8000
    elif info.language == "go":
        port = 8080
    strategy = "dockerfile_exists" if info.has_dockerfile else "generated_dockerfile"
    hint = (
        "Dockerfile found in the repository."
        if info.has_dockerfile
        else "Vela will generate a Dockerfile for this project."
    )
    needs_manual = (
        not info.has_dockerfile and info.language is SupportedLanguage.UNKNOWN
    )
    if needs_manual:
        hint = (
            "No Dockerfile or recognized project markers were found. "
            "Choose a language and build settings to continue."
        )
    return GitSourceAnalysis(
        git_branch=git_branch,
        container_port=port,
        container_name=None,
        env_vars={},
        start_command=None,
        language=info.language,
        framework=info.framework,
        has_dockerfile=info.has_dockerfile,
        build_strategy=strategy,
        summary_hint=hint,
        build_subdir=info.build_subdir,
        needs_manual_build_config=needs_manual,
    )


async def analyze_git_source(
    image_builder: DefaultImageBuilder,
    *,
    git_url: str,
    git_branch: str,
    access_token: str | None,
) -> GitSourceAnalysis:
    fixture = e2e_git_source_analysis_if_enabled(git_url, git_branch)
    if fixture is not None:
        return fixture

    project_path = await image_builder.clone_repository(
        git_url,
        branch=git_branch,
        access_token=access_token,
    )
    root = Path(project_path)
    parent = root.parent
    try:
        context = _collect_context_excerpts(root)
        if resolve_llm_config() is None:
            return _merge_env_fallback(_fallback_analysis(root, git_branch), context)
        commit = head_commit(root) or ""
        facts = _detected_facts_block(root, context)
        analysis = await _call_gemini(context, git_url, git_branch, facts, commit)
        enriched = _enrich_with_local_detection(analysis, root)
        return _merge_env_fallback(enriched, context)
    finally:
        from app.core.git.git_ops import rm_tree

        rm_tree(parent)


def sanitize_container_name(candidate: str | None) -> str | None:
    if not candidate:
        return None
    cleaned = re.sub(r"[^a-z0-9-]", "-", candidate.strip().lower())
    cleaned = re.sub(r"-+", "-", cleaned).strip("-")
    return cleaned[:128] if cleaned else None
