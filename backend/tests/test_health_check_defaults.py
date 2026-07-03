"""Default container health check configuration."""

from __future__ import annotations

from app.core.models import default_listen_port_health_check


def test_default_listen_port_health_check_targets_container_port() -> None:
    health_check = default_listen_port_health_check(8080)
    assert health_check.command[0] == "CMD-SHELL"
    shell_command = health_check.command[1]
    assert "127.0.0.1 8080" in shell_command or "127.0.0.1', 8080)" in shell_command
    assert "http://" not in shell_command
    assert health_check.start_period_s == 30
