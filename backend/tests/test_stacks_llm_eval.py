"""Eval harness for stack repo analysis (POST /api/stacks/analyze-repo).

Always-on tiers (offline, in the default pytest run):
- oracle: the deterministic extractor covers every golden's required env key
  over the collected context — a failure means the golden is unanswerable
  (context truncation or fixture bug), not that the LLM missed it.
- stubbed pipeline: full analyze_repo_stack path with generate_json stubbed,
  proving env vars survive end-to-end (the fallback merge fills what a
  silent LLM leaves out).

Live tier (opt-in, real LLM, costs money):
  VELA_LLM_EVAL=1 python -m pytest tests/test_stacks_llm_eval.py -v -s
Scores service/env/port coverage per fixture, fails on hard misses, and
appends a JSON line per fixture to tests/llm_eval_history.jsonl for trend.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.core.git.git_source_analysis import (
    _collect_context_excerpts,
    _extract_env_vars_from_context,
)
from app.core.llm.provider import resolve_llm_config
from app.core.stacks import repo_analysis
from app.core.stacks.repo_analysis import RepoStackAnalysis, analyze_repo_stack

HISTORY_PATH = Path(__file__).parent / "llm_eval_history.jsonl"

FIXTURES: list[dict] = [
    {
        "name": "python-simple",
        "files": {
            "README.md": (
                "# Tiny API\n\nFastAPI service.\n\n## Environment\n\n"
                "| Variable | Notes |\n|---|---|\n"
                "| `DATABASE_URL` | `postgresql://app:secret@db:5432/app` |\n"
                "| `WORKERS` | `4` |\n\n"
                "Run with `uvicorn main:app --port 8000`.\n"
            ),
            "requirements.txt": "fastapi\nuvicorn\n",
        },
        "services": [
            {"aliases": ["api", "app", "web"], "kind": "git", "port": 8000},
            {"aliases": ["db", "postgres"], "kind": "image", "port": 5432},
        ],
        "required_env": ["DATABASE_URL", "WORKERS"],
        "pinned_env": {
            "DATABASE_URL": "postgresql://app:secret@db:5432/app",
            "WORKERS": "4",
        },
    },
    {
        "name": "node-env-example",
        "files": {
            "README.md": (
                "# Demo\n\nNode service. See `.env.example` for configuration. "
                "Start with `npm start`.\n"
            ),
            ".env.example": "PORT=3000\nAPI_KEY=changeme\nSESSION_SECRET=\n",
            "package.json": (
                '{"name": "demo", "version": "1.0.0", "scripts": {"start": "node server.js"}}\n'
            ),
        },
        "services": [
            {"aliases": ["app", "web", "demo", "node"], "kind": "git", "port": 3000},
        ],
        "required_env": ["PORT", "API_KEY", "SESSION_SECRET"],
        "pinned_env": {"API_KEY": "changeme", "PORT": "3000"},
    },
    {
        "name": "monorepo-3svc",
        "files": {
            "README.md": (
                "# Big Service\n\nWeb app plus background worker.\n\n## Environment\n\n"
                "| Variable | Notes |\n|---|---|\n"
                "| `DATABASE_URL` | `postgresql://app@db:5432/app` |\n"
                "| `WORKER_CONCURRENCY` | `2` |\n"
                "| `WEB_PORT` | `8080` |\n"
            ),
            "requirements.txt": "fastapi\nuvicorn\ncelery\n",
        },
        "services": [
            {"aliases": ["web", "api", "frontend"], "kind": "git", "port": 8080},
            {"aliases": ["worker", "celery", "background"], "kind": "git"},
            {"aliases": ["db", "postgres"], "kind": "image", "port": 5432},
        ],
        "required_env": ["DATABASE_URL", "WORKER_CONCURRENCY", "WEB_PORT"],
        "pinned_env": {"WORKER_CONCURRENCY": "2", "WEB_PORT": "8080"},
    },
    {
        "name": "long-readme-midtable",
        "files": {
            "README.md": (
                "# Big App\n\n"
                + "\n".join(f"## Changelog {i}\n\nPatched item {i}.\n" for i in range(250))
                + "\n## Environment\n\n"
                "| Variable | Notes |\n|---|---|\n"
                "| `API_HOST` | `api.internal.example` |\n"
                "| `API_TOKEN` | `tok-123` |\n\nEnd of docs.\n"
            ),
            "package.json": '{"name": "big-app", "scripts": {"start": "node index.js"}}\n',
        },
        "services": [
            {"aliases": ["app", "web", "api"], "kind": "git"},
        ],
        "required_env": ["API_HOST", "API_TOKEN"],
        "pinned_env": {"API_TOKEN": "tok-123"},
    },
    {
        "name": "huge-readme-late-table",
        "files": {
            "README.md": (
                "# Huge App\n\n"
                + "\n".join(f"## Changelog {i}\n\nPatched item {i}.\n" for i in range(400))
                + "\n## Installation and Setup\n\n"
                + "This section is long enough to survive the section floor. " * 20
                + "\n\n## Environment\n\n"
                "| Variable | Notes |\n|---|---|\n"
                "| `LATE_DB_URL` | `postgresql://late:pw@db:5432/late` |\n"
                "| `LATE_TOKEN` | `tok-late-1` |\n\n"
                "End of docs.\n"
            ),
        },
        "services": [
            {"aliases": ["app", "web", "api"], "kind": "git"},
        ],
        "required_env": ["LATE_DB_URL", "LATE_TOKEN"],
        "pinned_env": {
            "LATE_DB_URL": "postgresql://late:pw@db:5432/late",
            "LATE_TOKEN": "tok-late-1",
        },
    },
    {
        "name": "monorepo-subdir",
        "files": {
            "README.md": (
                "# Monorepo\n\n"
                "Two subprojects in one repository:\n\n"
                "- `web/` — frontend (Node.js); env vars in `web/.env.example`.\n"
                "- `api/` — backend service (Python); built from `api/Dockerfile`.\n"
            ),
            "web/package.json": (
                '{"name": "web", "version": "1.0.0", "scripts": {"start": "node server.js"}}\n'
            ),
            "web/.env.example": "WEB_SESSION_SECRET=websess\nWEB_API_URL=http://api:8080\n",
            "api/Dockerfile": (
                "FROM python:3.12-slim\n"
                "WORKDIR /app\n"
                "COPY . .\n"
                "EXPOSE 8000\n"
                'CMD ["python", "main.py"]\n'
            ),
        },
        "services": [
            {"aliases": ["web", "frontend"], "kind": "git"},
            {"aliases": ["api", "backend", "service"], "kind": "git", "port": 8000},
        ],
        "required_env": ["WEB_SESSION_SECRET", "WEB_API_URL"],
        "pinned_env": {"WEB_API_URL": "http://api:8080"},
    },
]

STUB_PAYLOAD = {
    "services": [
        {
            "service_name": "web",
            "source_kind": "git",
            "source_ref": "",
            "container_port": 8000,
            "env_var_entries": [],
            "command": None,
            "public_route": True,
            "depends_on": ["db"],
        },
        {
            "service_name": "db",
            "source_kind": "image",
            "source_ref": "postgres:16",
            "container_port": 5432,
            "env_var_entries": [],
            "command": None,
            "public_route": False,
            "depends_on": None,
        },
    ],
    "summary_hint": "stubbed LLM response",
}


class _EvalImageBuilder:
    def __init__(self, root: Path) -> None:
        self._root = root

    async def clone_repository(
        self,
        git_url: str,
        *,
        branch: str = "main",
        access_token: str | None = None,
    ) -> str:
        _ = git_url, branch, access_token
        return str(self._root)


def _write_fixture(tmp_path: Path, fixture: dict) -> Path:
    root = tmp_path / fixture["name"] / "repo"
    root.mkdir(parents=True)
    for filename, content in fixture["files"].items():
        path = root / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return root


def _llm_eval_enabled() -> bool:
    return os.environ.get("VELA_LLM_EVAL", "").strip() == "1"


def _score(fixture: dict, analysis: RepoStackAnalysis) -> tuple[list[str], dict[str, str]]:
    hard_failures: list[str] = []
    services = {service.service_name.casefold(): service for service in analysis.services}
    env_union: dict[str, str] = {}
    for service in analysis.services:
        for key, value in service.env_vars.items():
            env_union.setdefault(key.casefold(), value)

    matched: set[str] = set()
    ports_ok = 0
    ports_total = 0
    for expected in fixture["services"]:
        aliases = {alias.casefold() for alias in expected["aliases"]}
        hit = next(
            (service for name, service in services.items() if name in aliases and service.source_kind == expected["kind"]),
            None,
        )
        if hit is None:
            hard_failures.append(f"service {expected['aliases'][0]} ({expected['kind']}) missing")
            continue
        matched.add(hit.service_name.casefold())
        if expected.get("port") is not None:
            ports_total += 1
            if hit.container_port == expected["port"]:
                ports_ok += 1

    env_found = [key for key in fixture["required_env"] if key.casefold() in env_union]
    for key in fixture["required_env"]:
        if key.casefold() not in env_union:
            hard_failures.append(f"env {key} missing")

    values_ok = 0
    values_total = 0
    for key, value in fixture["pinned_env"].items():
        values_total += 1
        if env_union.get(key.casefold()) == value:
            values_ok += 1

    metrics = {
        "services": f"{len(matched)}/{len(fixture['services'])}",
        "env": f"{len(env_found)}/{len(fixture['required_env'])}",
        "values": f"{values_ok}/{values_total}",
        "ports": f"{ports_ok}/{ports_total}" if ports_total else "-",
    }
    return hard_failures, metrics


def _record_history(fixture_name: str, metrics: dict[str, str], hard_failures: list[str]) -> None:
    config = resolve_llm_config()
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "provider": config.provider if config else None,
        "model": config.model if config else None,
        "fixture": fixture_name,
        **metrics,
        "hard_pass": not hard_failures,
    }
    with HISTORY_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry) + "\n")


@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda fixture: fixture["name"])
def test_oracle_required_env_reachable(fixture: dict, tmp_path: Path) -> None:
    root = _write_fixture(tmp_path, fixture)
    context = _collect_context_excerpts(root)
    extracted = _extract_env_vars_from_context(context)
    missing = [key for key in fixture["required_env"] if key not in extracted]
    assert not missing, f"golden unanswerable: context lacks {missing}"


async def test_pipeline_stubbed_llm_merges_env_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = FIXTURES[0]
    root = _write_fixture(tmp_path, fixture)

    captured: dict[str, str] = {}

    async def fake_generate_json(*, prompt: str, schema: dict) -> dict:
        _ = schema
        captured["prompt"] = prompt
        return STUB_PAYLOAD

    monkeypatch.setattr(repo_analysis, "generate_json", fake_generate_json)
    monkeypatch.delenv("VELA_E2E", raising=False)

    analysis = await analyze_repo_stack(
        _EvalImageBuilder(root),
        git_url="https://github.com/org/repo.git",
        git_branch="main",
        access_token=None,
    )

    assert analysis.manifest_kind == "llm"
    by_name = {service.service_name: service for service in analysis.services}
    assert set(by_name) == {"web", "db"}
    web = by_name["web"]
    assert {"DATABASE_URL", "WORKERS"} <= web.env_vars.keys()
    assert web.env_vars["DATABASE_URL"] == "postgresql://app:secret@db:5432/app"
    assert web.container_port == 8000
    assert by_name["db"].source_ref == "postgres:16"
    assert "Detected facts" in captured["prompt"]
    assert "DATABASE_URL" in captured["prompt"]


@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda fixture: fixture["name"])
@pytest.mark.skipif(not _llm_eval_enabled(), reason="set VELA_LLM_EVAL=1 for the live LLM eval")
async def test_llm_env_coverage(
    fixture: dict, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("VELA_E2E", raising=False)
    if resolve_llm_config() is None:
        pytest.skip("no LLM configured (VELA_GEMINI_API_KEY or VELA_VERTEX_API_KEY)")
    root = _write_fixture(tmp_path, fixture)
    analysis = await analyze_repo_stack(
        _EvalImageBuilder(root),
        git_url="https://github.com/org/repo.git",
        git_branch="main",
        access_token=None,
    )
    hard_failures, metrics = _score(fixture, analysis)
    line = " ".join(f"{name}={value}" for name, value in metrics.items())
    print(f"[llm-eval] {fixture['name']}: {line}")
    for failure in hard_failures:
        print(f"[llm-eval]   MISS: {failure}")
    _record_history(fixture["name"], metrics, hard_failures)
    assert not hard_failures, "; ".join(hard_failures)
