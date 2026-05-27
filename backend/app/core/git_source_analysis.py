"""Gemini-backed Git repository analysis for deploy form pre-fill."""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path

import httpx
from pydantic import ValidationError

from app.api.schemas import GitSourceAnalysis
from app.core.default_image_builder import DefaultImageBuilder
from app.core.exceptions import GitSourceAnalysisError
from app.core.project_analysis import analyze_project
from app.e2e_support import e2e_git_source_analysis_if_enabled

logger = logging.getLogger(__name__)

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_GEMINI_MODEL = "gemini-2.0-flash"
MAX_FILE_BYTES = 12_000
MAX_TOTAL_BYTES = 48_000

_CONTEXT_FILES = (
    "Dockerfile",
    "package.json",
    "pyproject.toml",
    "requirements.txt",
    "go.mod",
    "README.md",
)

GIT_SOURCE_ANALYSIS_PROMPT_V1 = """You analyze Git repositories for deployment on Vela (Docker containers behind Traefik public routes).

Given repository file excerpts, infer how the app should be deployed:
- container_port: TCP port the app listens on inside the container (e.g. 5173 for Vite, 8000 for FastAPI, 8080 for Go).
- container_name: short DNS-safe name derived from the repo (lowercase, hyphens).
- git_branch: keep the requested branch unless excerpts clearly indicate another default.
- env_vars: only suggest env vars clearly required for a minimal dev/demo run (empty object if none).
- start_command: optional CMD override tokens as a JSON array, or null to use the image default.
- language, framework: short labels or null.
- has_dockerfile: true if a Dockerfile exists in excerpts.
- build_strategy: "dockerfile_exists" if Dockerfile present, else "generated_dockerfile".
- summary_hint: one short sentence for the UI (max 120 chars).

Respond with JSON matching the schema exactly."""


def _gemini_api_key() -> str | None:
    key = os.environ.get("VELA_GEMINI_API_KEY", "").strip()
    return key or None


def _gemini_model() -> str:
    return os.environ.get("VELA_GEMINI_MODEL", DEFAULT_GEMINI_MODEL).strip() or DEFAULT_GEMINI_MODEL


def _collect_context_excerpts(project_root: Path) -> str:
    parts: list[str] = []
    total = 0
    for name in _CONTEXT_FILES:
        path = project_root / name
        if not path.is_file():
            continue
        raw = path.read_bytes()
        if len(raw) > MAX_FILE_BYTES:
            text = raw[:MAX_FILE_BYTES].decode("utf-8", errors="replace") + "\n…"
        else:
            text = raw.decode("utf-8", errors="replace")
        chunk = f"=== {name} ===\n{text.strip()}\n"
        if total + len(chunk) > MAX_TOTAL_BYTES:
            break
        parts.append(chunk)
        total += len(chunk)
    if not parts:
        info = analyze_project(project_root)
        parts.append(
            f"=== analysis ===\nlanguage={info.language}\n"
            f"has_dockerfile={info.has_dockerfile}\n"
            f"dependency_file={info.dependency_file}\n"
        )
    return "\n".join(parts)


def _analysis_json_schema() -> dict:
    """Gemini ``responseSchema`` subset (UPPERCASE types, ``nullable``, no type arrays)."""
    return {
        "type": "OBJECT",
        "properties": {
            "git_branch": {"type": "STRING", "nullable": True},
            "container_port": {"type": "INTEGER"},
            "container_name": {"type": "STRING", "nullable": True},
            "env_vars": {"type": "OBJECT"},
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
            "env_vars",
            "start_command",
            "language",
            "framework",
            "has_dockerfile",
            "build_strategy",
            "summary_hint",
        ],
    }


async def _call_gemini(context: str, git_url: str, git_branch: str) -> GitSourceAnalysis:
    api_key = _gemini_api_key()
    if api_key is None:
        raise GitSourceAnalysisError(
            "AI analysis is not configured on this server (missing VELA_GEMINI_API_KEY)."
        )

    model = _gemini_model()
    url = f"{GEMINI_API_BASE}/models/{model}:generateContent"
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {
                        "text": (
                            f"{GIT_SOURCE_ANALYSIS_PROMPT_V1}\n\n"
                            f"Repository: {git_url}\n"
                            f"Requested branch: {git_branch}\n\n"
                            f"{context}"
                        )
                    }
                ],
            }
        ],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": _analysis_json_schema(),
        },
    }
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                url,
                params={"key": api_key},
                json=payload,
            )
            response.raise_for_status()
    except httpx.HTTPError as exc:
        response_detail = ""
        if isinstance(exc, httpx.HTTPStatusError) and exc.response is not None:
            response_detail = exc.response.text[:240]
        logger.info(
            "Gemini analysis request failed: %s %s",
            exc,
            response_detail,
        )
        raise GitSourceAnalysisError(
            "Could not complete AI repository analysis. Try again later."
        ) from exc

    try:
        body = response.json()
        text = body["candidates"][0]["content"]["parts"][0]["text"]
        parsed = json.loads(text)
        return GitSourceAnalysis.model_validate(parsed)
    except (KeyError, IndexError, json.JSONDecodeError, ValidationError) as exc:
        logger.info("Gemini analysis response parse failed: %s", exc)
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
        if _gemini_api_key() is None:
            return _fallback_analysis(root, git_branch)
        return await _call_gemini(context, git_url, git_branch)
    finally:
        from app.core.git_ops import rm_tree

        rm_tree(parent)


def sanitize_container_name(candidate: str | None) -> str | None:
    if not candidate:
        return None
    cleaned = re.sub(r"[^a-z0-9-]", "-", candidate.strip().lower())
    cleaned = re.sub(r"-+", "-", cleaned).strip("-")
    return cleaned[:128] if cleaned else None
