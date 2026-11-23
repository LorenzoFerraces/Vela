from pathlib import Path

import yaml

COMPOSE = Path(__file__).resolve().parents[2] / "docker-compose.yml"

DB_URL = (
    "postgresql+asyncpg://${POSTGRES_USER:-vela}:${POSTGRES_PASSWORD:-vela}"
    "@postgres:5432/${POSTGRES_DB:-Vela}"
)


def test_ha_profile_services_exist() -> None:
    config = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    services = config["services"]
    assert services["api-ha"]["profiles"] == ["ha"]
    assert services["scheduler"]["profiles"] == ["ha"]
    assert services["api-ha"]["environment"]["VELA_BACKGROUND_LOOPS_ENABLED"] == "0"
    assert services["scheduler"]["environment"]["VELA_BACKGROUND_LOOPS_ENABLED"] == "1"
    assert "api" not in config["services"]["api"].get("profiles", [])


def test_ha_services_share_api_runtime_env() -> None:
    config = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    services = config["services"]
    assert services["api-ha"]["deploy"]["replicas"] == "${VELA_API_REPLICAS:-3}"
    for name in ("api-ha", "scheduler"):
        environment = services[name]["environment"]
        assert environment["VELA_DATABASE_URL"] == DB_URL
        assert (
            environment["VELA_TRAEFIK_DYNAMIC_FILE"]
            == "/etc/traefik/dynamic/traefik-http.yml"
        )
