"""Unit tests for container state change detection."""

from __future__ import annotations

from app.core.notifications.container_monitor import ContainerStateSnapshot
from app.core.enums import ContainerStatus, HealthStatus


def test_detect_change_running_to_dead_is_failure() -> None:
    state = ContainerStateSnapshot()
    state.update("c1", "app", ContainerStatus.RUNNING, HealthStatus.NONE)
    assert (
        state.detect_change("c1", ContainerStatus.DEAD, HealthStatus.NONE) == "failure"
    )


def test_detect_change_running_to_stopped_is_stop() -> None:
    state = ContainerStateSnapshot()
    state.update("c1", "app", ContainerStatus.RUNNING, HealthStatus.NONE)
    assert (
        state.detect_change("c1", ContainerStatus.STOPPED, HealthStatus.NONE) == "stop"
    )


def test_detect_change_restarting_to_dead_is_failure() -> None:
    state = ContainerStateSnapshot()
    state.update("c1", "app", ContainerStatus.RESTARTING, HealthStatus.NONE)
    assert (
        state.detect_change("c1", ContainerStatus.DEAD, HealthStatus.NONE) == "failure"
    )


def test_detect_change_healthy_to_unhealthy() -> None:
    state = ContainerStateSnapshot()
    state.update("c1", "app", ContainerStatus.RUNNING, HealthStatus.HEALTHY)
    assert (
        state.detect_change("c1", ContainerStatus.RUNNING, HealthStatus.UNHEALTHY)
        == "unhealthy"
    )


def test_detect_change_first_observation_is_silent() -> None:
    state = ContainerStateSnapshot()
    assert state.detect_change("c1", ContainerStatus.DEAD, HealthStatus.NONE) is None


def test_detect_change_paused_to_stopped_is_stop() -> None:
    state = ContainerStateSnapshot()
    state.update("c1", "app", ContainerStatus.PAUSED, HealthStatus.NONE)
    assert (
        state.detect_change("c1", ContainerStatus.STOPPED, HealthStatus.NONE) == "stop"
    )


def test_detect_disappeared_after_running() -> None:
    state = ContainerStateSnapshot()
    state.update("c1", "app", ContainerStatus.RUNNING, HealthStatus.NONE)
    assert state.detect_disappeared("c1") == "stop"


def test_detect_disappeared_after_already_stopped_is_silent() -> None:
    state = ContainerStateSnapshot()
    state.update("c1", "app", ContainerStatus.STOPPED, HealthStatus.NONE)
    assert state.detect_disappeared("c1") is None
