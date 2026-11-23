from pathlib import Path
import yaml

COMPOSE = Path(__file__).resolve().parents[2] / "docker-compose.yml"


def test_ha_profile_services_exist() -> None:
    config = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    services = config["services"]
    assert services["api-ha"]["profiles"] == ["ha"]
    assert services["scheduler"]["profiles"] == ["ha"]
    assert services["api-ha"]["environment"]["VELA_BACKGROUND_LOOPS_ENABLED"] == "0"
    assert services["scheduler"]["environment"]["VELA_BACKGROUND_LOOPS_ENABLED"] == "1"
    assert "api" not in config["services"]["api"].get("profiles", [])
