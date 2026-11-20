import pytest

from app.core.exceptions import RouteConfigurationError
from app.core.traffic.traefik_file_traffic_router import _path_rule


@pytest.mark.parametrize("prefix", ["/`", "/a`b", "/a\\b"])
def test_path_rule_rejects_traefik_expression_breakout(prefix: str) -> None:
    with pytest.raises(RouteConfigurationError):
        _path_rule(prefix)


def test_path_rule_accepts_normal_prefix() -> None:
    assert _path_rule("/apps/api") == "PathPrefix(`/apps/api`)"
