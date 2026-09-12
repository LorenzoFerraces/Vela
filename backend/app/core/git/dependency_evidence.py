"""Deterministic detection of external service dependencies from repo config files."""

from __future__ import annotations

import json
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from app.core.git.language_detection import IGNORE_DIR_NAMES
from app.core.models import ProjectInfo

MAX_EVIDENCE_FILES = 20
_WALK_DEPTH = 3
_FILE_BYTES = 12_000

KIND_DEFAULTS: dict[str, tuple[str, int]] = {
    "postgres": ("postgres:16", 5432),
    "mongo": ("mongo:7", 27017),
    "neo4j": ("neo4j:5", 7687),
    "redis": ("redis:7", 6379),
    "mysql": ("mysql:8", 3306),
    "mariadb": ("mariadb:11", 3306),
    "rabbitmq": ("rabbitmq:3-management", 5672),
}

# ponytail: ordered longest/most-specific first so mongodb+srv beats mongodb.
_URL_SCHEMES: tuple[tuple[str, str], ...] = (
    ("jdbc:postgresql:", "postgres"),
    ("postgresql://", "postgres"),
    ("postgres://", "postgres"),
    ("mariadb://", "mariadb"),
    ("mysql://", "mysql"),
    ("mongodb+srv://", "mongo"),
    ("mongodb://", "mongo"),
    ("neo4j://", "neo4j"),
    ("bolt://", "neo4j"),
    ("rediss://", "redis"),
    ("redis://", "redis"),
    ("amqps://", "rabbitmq"),
    ("amqp://", "rabbitmq"),
)
_URL_TOKEN = re.compile(
    r"(?:jdbc:postgresql:|postgresql://|postgres://|mariadb://|mysql://"
    r"|mongodb\+srv://|mongodb://|neo4j://|bolt://|rediss://|redis://"
    r"|amqps://|amqp://)\S*"
)

_JVM_ARTIFACTS: tuple[tuple[str, str], ...] = (
    ("postgresql", "postgres"),
    ("mariadb-java-client", "mariadb"),
    ("mysql-connector", "mysql"),
    ("mongodb-driver", "mongo"),
    ("mongo-java-driver", "mongo"),
    ("spring-boot-starter-data-mongodb", "mongo"),
    ("spring-boot-starter-data-neo4j", "neo4j"),
    ("neo4j-ogm", "neo4j"),
    ("neo4j-java-driver", "neo4j"),
    ("spring-boot-starter-amqp", "rabbitmq"),
    ("amqp-client", "rabbitmq"),
    ("spring-data-redis", "redis"),
    ("jedis", "redis"),
    ("lettuce", "redis"),
)
_PYTHON_PACKAGES: dict[str, str] = {
    "psycopg2": "postgres", "psycopg2-binary": "postgres", "psycopg": "postgres",
    "asyncpg": "postgres", "pymongo": "mongo", "motor": "mongo", "neo4j": "neo4j",
    "redis": "redis", "mysqlclient": "mysql", "pymysql": "mysql",
    "mysql-connector-python": "mysql", "pika": "rabbitmq", "amqp": "rabbitmq",
}
_NODE_PACKAGES: dict[str, str] = {
    "pg": "postgres", "postgres": "postgres", "mongodb": "mongo", "mongoose": "mongo",
    "neo4j-driver": "neo4j", "ioredis": "redis", "redis": "redis", "mysql2": "mysql",
    "amqplib": "rabbitmq",
}

_POM_DEPENDENCY = re.compile(r"<dependency>(.*?)</dependency>", re.DOTALL)
_POM_ARTIFACT = re.compile(r"<artifactId>\s*([^<]+?)\s*</artifactId>")
_POM_TEST_SCOPE = re.compile(r"<scope>\s*(?:test|provided)\s*</scope>")
_GRADLE_TEST = re.compile(r"^\s*test(?:Implementation|RuntimeOnly|Compile)")

_SPRING_CONFIG_NAMES = ("application.yml", "application.yaml", "application.properties")
_PROPERTY_LINE = re.compile(
    r"^\s*([A-Za-z0-9_.\-]+)\s*[=:]\s*(.+?)\s*$", re.MULTILINE
)


@dataclass(frozen=True)
class ServiceEvidence:
    kind: str
    image_ref: str
    port: int
    hostname: str | None
    env_key: str | None
    sources: tuple[str, ...]
    matched_lines: tuple[str, ...]


@dataclass
class _KindAccumulator:
    hostname: str | None = None
    port: int | None = None
    env_key: str | None = None
    sources: list[str] = field(default_factory=list)
    matched_lines: list[str] = field(default_factory=list)


def _read(path: Path) -> str:
    try:
        raw = path.read_bytes()
    except OSError:
        return ""
    return raw[:_FILE_BYTES].decode("utf-8", errors="replace")


def _redact_evidence_line(line: str) -> str:
    return re.sub(r"(://)[^/@\s]+@", r"\1[REDACTED]@", line)


def _normalize_property_key(dotted: str) -> str:
    return re.sub(r"[.\-]", "_", dotted).upper()


def _match_url(token: str) -> tuple[str, str | None, int | None] | None:
    cleaned = token.strip().strip("\"'`,")
    for prefix, kind in _URL_SCHEMES:
        if cleaned.lower().startswith(prefix):
            authority = cleaned[len(prefix):].lstrip("/").split("/", 1)[0].split("?", 1)[0]
            if "@" in authority:
                authority = authority.rsplit("@", 1)[1]
            host = authority
            port: int | None = None
            if ":" in authority:
                candidate_host, _, port_text = authority.rpartition(":")
                if port_text.isdigit():
                    host, port = candidate_host, int(port_text)
            return kind, (host or None), port
    return None


def _flatten_yaml(text: str) -> list[tuple[str, str]]:
    stack: list[tuple[int, str]] = []
    leaves: list[tuple[str, str]] = []
    for raw_line in text.splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip())
        stripped = raw_line.strip()
        if ":" not in stripped:
            continue
        key, _, value = stripped.partition(":")
        key, value = key.strip(), value.strip()
        while stack and stack[-1][0] >= indent:
            stack.pop()
        if value:
            dotted = ".".join([part for _, part in stack] + [key])
            leaves.append((dotted, value.strip("\"'")))
        else:
            stack.append((indent, key))
    return leaves


def _kinds_in_text(text: str, rules: tuple[tuple[str, str], ...]) -> set[str]:
    lowered = text.lower()
    return {kind for needle, kind in rules if needle in lowered}


def _scan_pom(text: str) -> tuple[set[str], list[str]]:
    kinds: set[str] = set()
    lines: list[str] = []
    for block in _POM_DEPENDENCY.findall(text):
        if _POM_TEST_SCOPE.search(block):
            continue
        artifacts = _POM_ARTIFACT.findall(block)
        block_kinds = {kind for artifact in artifacts for kind in _kinds_in_text(artifact, _JVM_ARTIFACTS)}
        if block_kinds:
            kinds |= block_kinds
            lines.append(", ".join(artifacts))
    return kinds, lines


def _scan_gradle(text: str) -> tuple[set[str], list[str]]:
    kinds: set[str] = set()
    lines: list[str] = []
    for line in text.splitlines():
        if _GRADLE_TEST.match(line):
            continue
        line_kinds = _kinds_in_text(line, _JVM_ARTIFACTS)
        if line_kinds:
            kinds |= line_kinds
            lines.append(line.strip())
    return kinds, lines


def _scan_python(text: str) -> tuple[set[str], list[str]]:
    kinds: set[str] = set()
    lines: list[str] = []
    for line in text.splitlines():
        token = re.split(r"[=<>!\[;\s]", line.strip(), maxsplit=1)[0].lower()
        kind = _PYTHON_PACKAGES.get(token)
        if kind:
            kinds.add(kind)
            lines.append(line.strip())
    return kinds, lines


def _normalize_python_spec(spec: str) -> str:
    name = spec.strip().strip("\"'")
    name = re.split(r"[<>=!~\[;@\s]", name, maxsplit=1)[0]
    return name.strip().lower().replace("_", "-")


def _scan_pyproject(text: str) -> tuple[set[str], list[str]]:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return set(), []
    specs: list[str] = []
    project = data.get("project")
    if isinstance(project, dict):
        for key in ("dependencies", "optional-dependencies"):
            value = project.get(key)
            if key == "dependencies" and isinstance(value, list):
                specs.extend(item for item in value if isinstance(item, str))
            elif key == "optional-dependencies" and isinstance(value, dict):
                for group in value.values():
                    if isinstance(group, list):
                        specs.extend(item for item in group if isinstance(item, str))
    poetry = (data.get("tool") or {}).get("poetry") if isinstance(data.get("tool"), dict) else None
    if isinstance(poetry, dict):
        for section in ("dependencies", "dev-dependencies"):
            table = poetry.get(section)
            if isinstance(table, dict):
                specs.extend(str(name) for name in table)
        groups = poetry.get("group")
        if isinstance(groups, dict):
            for group in groups.values():
                if isinstance(group, dict) and isinstance(group.get("dependencies"), dict):
                    specs.extend(str(name) for name in group["dependencies"])

    kinds: set[str] = set()
    lines: list[str] = []
    for spec in specs:
        kind = _PYTHON_PACKAGES.get(_normalize_python_spec(spec))
        if kind:
            kinds.add(kind)
            lines.append(spec)
    return kinds, lines


def _scan_node(text: str) -> tuple[set[str], list[str]]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return set(), []
    deps = {**(data.get("dependencies") or {}), **(data.get("devDependencies") or {})}
    kinds: set[str] = set()
    lines: list[str] = []
    for key in deps:
        kind = _NODE_PACKAGES.get(key)
        if kind:
            kinds.add(kind)
            lines.append(key)
    return kinds, lines


def _scan_spring(text: str, is_properties: bool) -> tuple[dict[str, tuple[str | None, int | None, str | None]], list[str]]:
    found: dict[str, tuple[str | None, int | None, str | None]] = {}
    lines: list[str] = []
    pairs = _flatten_yaml(text) if not is_properties else [
        (key, value) for key, value in (m.groups() for m in _PROPERTY_LINE.finditer(text))
    ]
    for dotted_key, value in pairs:
        match = _match_url(value)
        if match is None:
            continue
        kind, host, port = match
        env_key = _normalize_property_key(dotted_key)
        found.setdefault(kind, (host, port, env_key))
        lines.append(f"{dotted_key}={value}")
        lines.append(f"{env_key}={value}")
    return found, lines


def _scan_url_only(text: str) -> tuple[dict[str, tuple[str | None, int | None]], list[str]]:
    found: dict[str, tuple[str | None, int | None]] = {}
    lines: list[str] = []
    for line in text.splitlines():
        for token in _URL_TOKEN.findall(line):
            match = _match_url(token)
            if match is None:
                continue
            kind, host, port = match
            found.setdefault(kind, (host, port))
            lines.append(line.strip())
    return found, lines


def _walk_files(root: Path, info: ProjectInfo | None) -> list[Path]:
    roots: list[Path] = []
    if info is not None and info.build_subdir:
        candidate = root / info.build_subdir
        if candidate.is_dir():
            roots.append(candidate)
    roots.append(root)

    found: list[Path] = []
    seen: set[Path] = set()

    def visit(directory: Path, depth: int) -> None:
        if depth > _WALK_DEPTH or len(found) >= MAX_EVIDENCE_FILES:
            return
        try:
            children = sorted(directory.iterdir(), key=lambda item: item.name)
        except OSError:
            return
        for child in children:
            if len(found) >= MAX_EVIDENCE_FILES:
                return
            if child.is_symlink():
                continue
            if child.is_dir():
                if child.name in IGNORE_DIR_NAMES or child.name.startswith("."):
                    continue
                visit(child, depth + 1)
            elif child.is_file() and _is_candidate(child.name) and child not in seen:
                seen.add(child)
                found.append(child)

    for base in roots:
        visit(base, 0)
    return found


def _is_candidate(name: str) -> bool:
    lowered = name.lower()
    return (
        lowered in {"pom.xml", "build.gradle", "build.gradle.kts", "requirements.txt",
                    "pyproject.toml", "pipfile", "package.json", ".env.example", "dockerfile"}
        or lowered in _SPRING_CONFIG_NAMES
        or lowered.startswith("application-") and lowered.endswith((".yml", ".yaml", ".properties"))
    )


def scan_dependency_evidence(root: Path, info: ProjectInfo | None = None) -> list[ServiceEvidence]:
    """One ServiceEvidence per detected external-service kind, URL evidence preferred."""
    kinds: dict[str, _KindAccumulator] = {}

    def record(kind: str, *, hostname: str | None, port: int | None, env_key: str | None,
               source: str, lines: list[str]) -> None:
        entry = kinds.setdefault(kind, _KindAccumulator())
        if hostname is not None and entry.hostname is None:
            entry.hostname = hostname
        if port is not None and entry.port is None:
            entry.port = port
        if env_key is not None and entry.env_key is None:
            entry.env_key = env_key
        if source not in entry.sources:
            entry.sources.append(source)
        for line in lines:
            redacted_line = _redact_evidence_line(line)
            if redacted_line not in entry.matched_lines:
                entry.matched_lines.append(redacted_line)

    for path in _walk_files(root, info):
        relative = path.relative_to(root).as_posix()
        text = _read(path)
        if not text:
            continue
        name = path.name.lower()

        if name == "pom.xml":
            artifact_kinds, lines = _scan_pom(text)
            for kind in artifact_kinds:
                record(kind, hostname=None, port=None, env_key=None, source=relative, lines=lines)
        elif name.startswith("build.gradle"):
            artifact_kinds, lines = _scan_gradle(text)
            for kind in artifact_kinds:
                record(kind, hostname=None, port=None, env_key=None, source=relative, lines=lines)
        elif name == "pyproject.toml":
            artifact_kinds, lines = _scan_pyproject(text)
            for kind in artifact_kinds:
                record(kind, hostname=None, port=None, env_key=None, source=relative, lines=lines)
        elif name in {"requirements.txt", "pipfile"}:
            artifact_kinds, lines = _scan_python(text)
            for kind in artifact_kinds:
                record(kind, hostname=None, port=None, env_key=None, source=relative, lines=lines)
        elif name == "package.json":
            artifact_kinds, lines = _scan_node(text)
            for kind in artifact_kinds:
                record(kind, hostname=None, port=None, env_key=None, source=relative, lines=lines)
        elif name in _SPRING_CONFIG_NAMES or (name.startswith("application-")):
            spring_found, lines = _scan_spring(text, is_properties=name.endswith(".properties"))
            for kind, (host, port, env_key) in spring_found.items():
                record(kind, hostname=host, port=port, env_key=env_key, source=relative, lines=lines)
        else:
            url_found, lines = _scan_url_only(text)
            for kind, (host, port) in url_found.items():
                record(kind, hostname=host, port=port, env_key=None, source=relative, lines=lines)

        if name == "pom.xml" or name.startswith("build.gradle"):
            url_found, url_lines = _scan_url_only(text)
            for kind, (host, port) in url_found.items():
                record(kind, hostname=host, port=port, env_key=None, source=relative, lines=url_lines)

    evidence: list[ServiceEvidence] = []
    for kind in sorted(kinds):
        image_ref, default_port = KIND_DEFAULTS[kind]
        entry = kinds[kind]
        evidence.append(ServiceEvidence(
            kind=kind,
            image_ref=image_ref,
            port=int(entry.port or default_port),
            hostname=entry.hostname,
            env_key=entry.env_key,
            sources=tuple(entry.sources),
            matched_lines=tuple(entry.matched_lines),
        ))
    return evidence
