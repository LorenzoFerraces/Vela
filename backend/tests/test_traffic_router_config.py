import pytest

from app.api.deps import validate_traffic_router_config
from app.core.exceptions import TrafficRouterError


def test_kubernetes_is_rejected_with_supported_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VELA_TRAFFIC_ROUTER", "kubernetes")
    with pytest.raises(TrafficRouterError) as excinfo:
        validate_traffic_router_config()
    assert "use noop or traefik_file" in str(excinfo.value)
    assert "Unsupported" in str(excinfo.value)


@pytest.mark.parametrize("mode", ["noop", "traefik_file"])
def test_supported_modes_are_accepted(mode: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VELA_TRAFFIC_ROUTER", mode)
    monkeypatch.setenv("VELA_TRAEFIK_DYNAMIC_FILE", "/tmp/traefik-http.yml")
    validate_traffic_router_config()
