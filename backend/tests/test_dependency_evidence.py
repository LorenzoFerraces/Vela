from __future__ import annotations

from pathlib import Path

from app.core.git.dependency_evidence import (
    ServiceEvidence,
    classify_host,
    reconcile_detected_services,
    scan_dependency_evidence,
)
from app.db.models import StackService


def _write(root: Path, files: dict[str, str]) -> Path:
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return root


def test_pom_artifacts_map_to_kinds(tmp_path: Path) -> None:
    root = _write(tmp_path, {
        "pom.xml": (
            "<project><dependencies>"
            "<dependency><groupId>org.postgresql</groupId>"
            "<artifactId>postgresql</artifactId></dependency>"
            "<dependency><artifactId>mongodb-driver-sync</artifactId></dependency>"
            "<dependency><artifactId>neo4j-ogm-core</artifactId></dependency>"
            "</dependencies></project>"
        ),
    })
    kinds = {e.kind for e in scan_dependency_evidence(root)}
    assert {"postgres", "mongo", "neo4j"} <= kinds


def test_pom_jpa_alone_does_not_imply_postgres(tmp_path: Path) -> None:
    root = _write(tmp_path, {
        "pom.xml": (
            "<project><dependencies>"
            "<dependency><artifactId>spring-boot-starter-data-jpa</artifactId></dependency>"
            "</dependencies></project>"
        ),
    })
    assert scan_dependency_evidence(root) == []


def test_pom_test_scope_ignored(tmp_path: Path) -> None:
    root = _write(tmp_path, {
        "pom.xml": (
            "<project><dependencies>"
            "<dependency><artifactId>postgresql</artifactId><scope>test</scope></dependency>"
            "</dependencies></project>"
        ),
    })
    assert scan_dependency_evidence(root) == []


def test_gradle_kotlin_dsl_and_test_scope(tmp_path: Path) -> None:
    root = _write(tmp_path, {
        "build.gradle.kts": (
            'dependencies {\n'
            '    implementation("org.postgresql:postgresql")\n'
            '    testImplementation("org.testcontainers:postgresql")\n'
            '}\n'
        ),
    })
    evidence = scan_dependency_evidence(root)
    assert [e.kind for e in evidence] == ["postgres"]


def test_application_properties_url_yields_host_and_env_key(tmp_path: Path) -> None:
    root = _write(tmp_path, {
        "src/main/resources/application.properties": (
            "spring.datasource.url=jdbc:postgresql://localhost:5432/commit\n"
            "spring.data.mongodb.uri=mongodb://localhost:27017/commit\n"
            "spring.neo4j.uri=bolt://localhost:7687\n"
        ),
    })
    by_kind = {e.kind: e for e in scan_dependency_evidence(root)}
    assert by_kind["postgres"].hostname == "localhost"
    assert by_kind["postgres"].env_key == "SPRING_DATASOURCE_URL"
    assert by_kind["postgres"].port == 5432
    assert by_kind["mongo"].hostname == "localhost"
    assert by_kind["neo4j"].hostname == "localhost"


def test_application_yaml_nested_url(tmp_path: Path) -> None:
    root = _write(tmp_path, {
        "src/main/resources/application.yml": (
            "spring:\n"
            "  datasource:\n"
            "    url: jdbc:postgresql://localhost:5432/commit\n"
            "  neo4j:\n"
            "    uri: bolt://localhost:7687\n"
        ),
    })
    by_kind = {e.kind: e for e in scan_dependency_evidence(root)}
    assert by_kind["postgres"].env_key == "SPRING_DATASOURCE_URL"
    assert by_kind["neo4j"].env_key == "SPRING_NEO4J_URI"


def test_python_and_node_manifests(tmp_path: Path) -> None:
    py = _write(tmp_path / "py", {"requirements.txt": "fastapi\npsycopg2-binary\npymongo\n"})
    assert {"postgres", "mongo"} <= {e.kind for e in scan_dependency_evidence(py)}
    node = _write(tmp_path / "node", {
        "package.json": '{"dependencies": {"pg": "^8", "ioredis": "^5"}}',
    })
    assert {"postgres", "redis"} <= {e.kind for e in scan_dependency_evidence(node)}


def test_pyproject_pep621_dependencies(tmp_path: Path) -> None:
    root = _write(tmp_path, {
        "pyproject.toml": (
            "[project]\n"
            'dependencies = ["psycopg2>=2.9", "redis>=5"]\n'
        ),
    })
    assert {"postgres", "redis"} <= {e.kind for e in scan_dependency_evidence(root)}


def test_build_subdir_is_scanned(tmp_path: Path) -> None:
    from app.core.git.language_detection import analyze_project

    root = _write(tmp_path, {
        "README.md": "# App\n",
        "backend/pom.xml": (
            "<project><dependencies>"
            "<dependency><artifactId>postgresql</artifactId></dependency>"
            "</dependencies></project>"
        ),
    })
    info = analyze_project(root)
    kinds = {e.kind for e in scan_dependency_evidence(root, info)}
    assert "postgres" in kinds


def test_one_evidence_per_kind_dedup(tmp_path: Path) -> None:
    root = _write(tmp_path, {
        "pom.xml": "<project><dependencies><dependency><artifactId>postgresql</artifactId></dependency></dependencies></project>",
        "requirements.txt": "psycopg2\n",
    })
    postgres = [e for e in scan_dependency_evidence(root) if e.kind == "postgres"]
    assert len(postgres) == 1


def test_no_evidence_for_plain_repo(tmp_path: Path) -> None:
    root = _write(tmp_path, {"README.md": "# Hi\n", "package.json": '{"dependencies": {"express": "^4"}}'})
    assert scan_dependency_evidence(root) == []


def _app(name: str = "web", env: dict[str, str] | None = None) -> StackService:
    return StackService(
        service_name=name, source_kind="git", source_ref="https://github.com/o/r.git",
        git_branch="main", container_port=8080, env_vars=env or {}, command=None,
        public_route=True, depends_on=None, volumes=[],
    )


def _evidence(kind: str, hostname: str | None, env_key: str | None = None) -> ServiceEvidence:
    from app.core.git.dependency_evidence import KIND_DEFAULTS
    image_ref, port = KIND_DEFAULTS[kind]
    return ServiceEvidence(kind=kind, image_ref=image_ref, port=port, hostname=hostname,
                           env_key=env_key, sources=("backend/pom.xml",), matched_lines=())


def test_classify_host() -> None:
    assert classify_host("localhost") == "local"
    assert classify_host("127.0.0.1") == "local"
    assert classify_host(None) == "local"
    assert classify_host("db") == "sibling"
    assert classify_host("cluster0.abc.mongodb.net") == "external"


def test_reconcile_appends_missing_local_services() -> None:
    services = [_app(env={"SPRING_DATASOURCE_URL": "jdbc:postgresql://localhost:5432/commit"})]
    evidence = [_evidence("postgres", "localhost"), _evidence("neo4j", "localhost")]
    warnings: list[str] = []
    out, warns, detected = reconcile_detected_services(services, evidence, warnings)
    names = {s.service_name for s in out}
    assert {"web", "postgres", "neo4j"} <= names
    assert detected == ("postgres", "neo4j")
    web = next(s for s in out if s.service_name == "web")
    assert set(web.depends_on or []) == {"postgres", "neo4j"}
    assert web.env_vars["SPRING_DATASOURCE_URL"] == "jdbc:postgresql://postgres:5432/commit"
    assert any("postgres" in w for w in warns)


def test_reconcile_skips_external_host() -> None:
    services = [_app()]
    evidence = [_evidence("mongo", "cluster0.abc.mongodb.net")]
    out, warns, detected = reconcile_detected_services(services, evidence, [])
    assert detected == ()
    assert {s.service_name for s in out} == {"web"}
    assert any("external" in w.lower() or "managed" in w.lower() for w in warns)


def test_reconcile_does_not_duplicate_covered_kind() -> None:
    db = StackService(
        service_name="db", source_kind="image", source_ref="postgres:16", git_branch=None,
        container_port=5432, env_vars={}, command=None, public_route=False,
        depends_on=None, volumes=[],
    )
    services = [_app(env={"DATABASE_URL": "postgres://localhost:5432/app"}), db]
    evidence = [_evidence("postgres", "localhost")]
    out, _, detected = reconcile_detected_services(services, evidence, [])
    assert detected == ()
    web = next(s for s in out if s.service_name == "web")
    assert web.env_vars["DATABASE_URL"] == "postgres://db:5432/app"
