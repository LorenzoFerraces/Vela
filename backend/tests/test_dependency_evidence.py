from __future__ import annotations

from pathlib import Path

from app.core.git.dependency_evidence import scan_dependency_evidence


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
