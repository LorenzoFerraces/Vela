"""Deterministic detection of external service dependencies from repo config files."""

from __future__ import annotations

import json
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from app.core.git.language_detection import IGNORE_DIR_NAMES
from app.core.models import ProjectInfo
from app.db.models import StackService

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
_SPRING_PLACEHOLDER = re.compile(
    r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?:(?::|-)([^}]*))?\}"
)
_JDBC_DB_NAME = re.compile(r"/([^/?]+)(?:\?|$)")


@dataclass(frozen=True)
class ServiceEvidence:
    kind: str
    image_ref: str
    port: int
    hostname: str | None
    env_key: str | None
    sources: tuple[str, ...]
    matched_lines: tuple[str, ...]
    container_env_vars: tuple[tuple[str, str], ...] = ()


@dataclass
class _KindAccumulator:
    hostname: str | None = None
    port: int | None = None
    env_key: str | None = None
    sources: list[str] = field(default_factory=list)
    matched_lines: list[str] = field(default_factory=list)
    container_env_vars: dict[str, str] = field(default_factory=dict)


def _read(path: Path) -> str:
    try:
        raw = path.read_bytes()
    except OSError:
        return ""
    return raw[:_FILE_BYTES].decode("utf-8", errors="replace")


def _redact_evidence_line(line: str) -> str:
    return re.sub(r"(://)[^@\s]*@", r"\1[REDACTED]@", line)


def _normalize_property_key(dotted: str) -> str:
    return re.sub(r"[.\-]", "_", dotted).upper()


def _resolve_spring_placeholder(value: str) -> tuple[str, list[tuple[str, str]]]:
    """Resolve ``${ENV:default}`` placeholders; return value and env defaults."""
    env_defaults: list[tuple[str, str]] = []
    for match in _SPRING_PLACEHOLDER.finditer(value):
        env_name = match.group(1)
        default = (match.group(2) or "").strip()
        if default:
            env_defaults.append((env_name, default))
    resolved = _SPRING_PLACEHOLDER.sub(
        lambda match: (match.group(2) or "").strip(),
        value,
    )
    return resolved, env_defaults


def _spring_property_pairs(text: str, is_properties: bool) -> list[tuple[str, str]]:
    if is_properties:
        return [
            (key, value)
            for key, value in (match.groups() for match in _PROPERTY_LINE.finditer(text))
        ]
    return _flatten_yaml(text)


def _postgres_container_env_from_spring(text: str, is_properties: bool) -> dict[str, str]:
    jdbc_url: str | None = None
    username: str | None = None
    password: str | None = None
    for dotted_key, value in _spring_property_pairs(text, is_properties):
        resolved, _ = _resolve_spring_placeholder(value)
        if dotted_key == "spring.datasource.url":
            jdbc_url = resolved
        elif dotted_key == "spring.datasource.username":
            username = resolved
        elif dotted_key == "spring.datasource.password":
            password = resolved
    env_vars: dict[str, str] = {}
    if jdbc_url:
        db_match = _JDBC_DB_NAME.search(jdbc_url)
        if db_match:
            env_vars["POSTGRES_DB"] = db_match.group(1)
    if username:
        env_vars["POSTGRES_USER"] = username
    if password:
        env_vars["POSTGRES_PASSWORD"] = password
    return env_vars


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


def _scan_pom(text: str) -> dict[str, list[str]]:
    by_kind: dict[str, list[str]] = {}
    for block in _POM_DEPENDENCY.findall(text):
        if _POM_TEST_SCOPE.search(block):
            continue
        artifacts = _POM_ARTIFACT.findall(block)
        block_kinds = {kind for artifact in artifacts for kind in _kinds_in_text(artifact, _JVM_ARTIFACTS)}
        for kind in block_kinds:
            by_kind.setdefault(kind, []).append(", ".join(artifacts))
    return by_kind


def _scan_gradle(text: str) -> dict[str, list[str]]:
    by_kind: dict[str, list[str]] = {}
    in_test = False
    for line in text.splitlines():
        if in_test:
            if ")" in line:
                in_test = False
            continue
        if _GRADLE_TEST.match(line):
            if ")" not in line:
                in_test = True
            continue
        for kind in _kinds_in_text(line, _JVM_ARTIFACTS):
            by_kind.setdefault(kind, []).append(line.strip())
    return by_kind


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


def _scan_spring(
    text: str,
    is_properties: bool,
) -> tuple[
    dict[str, tuple[str | None, int | None, str | None]],
    dict[str, list[str]],
    list[str],
]:
    found: dict[str, tuple[str | None, int | None, str | None]] = {}
    lines: dict[str, list[str]] = {}
    app_env_lines: list[str] = []
    for dotted_key, value in _spring_property_pairs(text, is_properties):
        resolved, env_defaults = _resolve_spring_placeholder(value)
        for env_name, default in env_defaults:
            app_env_lines.append(f"{env_name}={default}")
        match = _match_url(resolved)
        if match is None:
            continue
        kind, host, port = match
        env_key = _normalize_property_key(dotted_key)
        found.setdefault(kind, (host, port, env_key))
        lines.setdefault(kind, []).extend(
            [f"{dotted_key}={value}", f"{env_key}={resolved}"]
        )
    if app_env_lines:
        for kind_lines in lines.values():
            kind_lines.extend(app_env_lines)
    return found, lines, app_env_lines


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
            artifact_lines = _scan_pom(text)
            for kind, lines in artifact_lines.items():
                record(kind, hostname=None, port=None, env_key=None, source=relative, lines=lines)
        elif name.startswith("build.gradle"):
            artifact_lines = _scan_gradle(text)
            for kind, lines in artifact_lines.items():
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
            is_properties = name.endswith(".properties")
            spring_found, spring_lines, app_env_lines = _scan_spring(text, is_properties)
            postgres_container_env = _postgres_container_env_from_spring(text, is_properties)
            for kind, (host, port, env_key) in spring_found.items():
                record(
                    kind,
                    hostname=host,
                    port=port,
                    env_key=env_key,
                    source=relative,
                    lines=spring_lines.get(kind, []) + app_env_lines,
                )
            if postgres_container_env:
                entry = kinds.setdefault("postgres", _KindAccumulator())
                entry.container_env_vars.update(postgres_container_env)
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
            container_env_vars=tuple(entry.container_env_vars.items()),
        ))
    return evidence


_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "0.0.0.0", "::1", ""})

_KIND_ALIASES: dict[str, frozenset[str]] = {
    "postgres": frozenset({"postgres", "postgresql", "db", "database", "rdbms"}),
    "mongo": frozenset({"mongo", "mongodb"}),
    "neo4j": frozenset({"neo4j", "graph"}),
    "redis": frozenset({"redis", "cache"}),
    "mysql": frozenset({"mysql"}),
    "mariadb": frozenset({"mariadb"}),
    "rabbitmq": frozenset({"rabbitmq", "rabbit", "amqp", "queue"}),
}
_IMAGE_FAMILY: dict[str, tuple[str, ...]] = {
    "postgres": ("postgres",),
    "mongo": ("mongo",),
    "neo4j": ("neo4j",),
    "redis": ("redis",),
    "mysql": ("mysql",),
    "mariadb": ("mariadb",),
    "rabbitmq": ("rabbitmq",),
}


def classify_host(hostname: str | None) -> str:
    if hostname is None:
        return "local"
    host = hostname.strip().strip("[]").lower()
    if host in _LOCAL_HOSTS:
        return "local"
    if "." in host:
        return "external"
    return "sibling"


def _covering_service(services: list[StackService], kind: str) -> StackService | None:
    aliases = _KIND_ALIASES.get(kind, frozenset())
    families = _IMAGE_FAMILY.get(kind, ())
    for service in services:
        if service.service_name.casefold() in aliases:
            return service
        ref = (service.source_ref or "").casefold()
        if service.source_kind == "image" and any(ref.startswith(family) for family in families):
            return service
    return None


def _repo_built_services(services: list[StackService]) -> list[StackService]:
    return [
        service
        for service in services
        if service.source_kind in {"git", "dockerfile_template"}
    ]


def _primary_app_service(
    services: list[StackService],
    *,
    kind: str,
) -> StackService | None:
    built_services = _repo_built_services(services)
    if not built_services:
        return None
    for service in built_services:
        for value in service.env_vars.values():
            for token in _URL_TOKEN.findall(value):
                parsed = _match_url(token)
                if parsed is not None and parsed[0] == kind:
                    return service
    return max(
        built_services,
        key=lambda service: (
            service.public_route,
            len(service.depends_on or []),
            len(service.env_vars),
        ),
    )


def _app_env_from_matched_lines(lines: tuple[str, ...]) -> dict[str, str]:
    env_vars: dict[str, str] = {}
    for line in lines:
        if "=" not in line or line.startswith("spring."):
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key and key[0].isalpha() and "." not in key:
            env_vars[key] = value
    return env_vars


def _env_value_from_evidence(item: ServiceEvidence) -> str | None:
    if item.env_key is None:
        return None
    prefix = f"{item.env_key}="
    for line in item.matched_lines:
        if line.startswith(prefix):
            return line[len(prefix) :]
    return None


def _rewrite_local_host(value: str, kind: str, replacement: str) -> str:
    def replace(match: re.Match[str]) -> str:
        token = match.group(0)
        info = _match_url(token)
        if info is None or info[0] != kind:
            return token
        host = info[1]
        if host is None or classify_host(host) == "external":
            return token
        return re.sub(
            rf"(://(?:[^/@]*@)?){re.escape(host)}(?=[:/]|$)",
            rf"\1{replacement}",
            token,
            count=1,
        )

    return _URL_TOKEN.sub(replace, value)


def reconcile_detected_services(
    services: list[StackService],
    evidence: list[ServiceEvidence],
    warnings: list[str],
) -> tuple[list[StackService], list[str], tuple[str, ...]]:
    result = list(services)
    new_warnings = list(warnings)
    detected_names: list[str] = []
    existing_names = {service.service_name.casefold() for service in result}

    for item in evidence:
        host_class = classify_host(item.hostname)
        if host_class == "external":
            new_warnings.append(
                f"{item.kind} appears to use an external/managed host"
                f"{' (' + item.hostname + ')' if item.hostname else ''}; no service added."
            )
            continue

        covering = _covering_service(result, item.kind)
        if covering is None:
            name = item.kind
            suffix = 2
            while name.casefold() in existing_names:
                name = f"{item.kind}-{suffix}"
                suffix += 1
            existing_names.add(name.casefold())
            result.append(StackService(
                service_name=name,
                source_kind="image",
                source_ref=item.image_ref,
                git_branch=None,
                container_port=item.port,
                env_vars={},
                command=None,
                public_route=False,
                depends_on=None,
                volumes=[],
            ))
            detected_names.append(name)
            new_warnings.append(
                f"Added {name} ({item.image_ref}) — detected in "
                f"{', '.join(item.sources) or 'repo config'} but missing from the AI analysis."
            )
            covering = result[-1]

        target_name = covering.service_name
        app_service = _primary_app_service(result, kind=item.kind)
        if app_service is not None and app_service.service_name.casefold() != target_name.casefold():
            deps = list(app_service.depends_on or [])
            if target_name not in deps:
                deps.append(target_name)
            app_service.depends_on = deps
        if item.container_env_vars and covering.source_kind == "image":
            merged = dict(covering.env_vars)
            for key, value in item.container_env_vars:
                merged.setdefault(key, value)
            covering.env_vars = merged
        if app_service is not None and item.env_key:
            raw_value = _env_value_from_evidence(item)
            if raw_value and item.env_key not in app_service.env_vars:
                app_service.env_vars[item.env_key] = _rewrite_local_host(
                    raw_value,
                    item.kind,
                    target_name,
                )
        if app_service is not None:
            for key, value in _app_env_from_matched_lines(item.matched_lines).items():
                if key not in app_service.env_vars:
                    rewritten = _rewrite_local_host(value, item.kind, target_name)
                    app_service.env_vars[key] = rewritten
        for service in _repo_built_services(result):
            rewritten = {
                key: _rewrite_local_host(value, item.kind, target_name)
                for key, value in service.env_vars.items()
            }
            if rewritten != service.env_vars:
                service.env_vars = rewritten

    return result, new_warnings, tuple(detected_names)
