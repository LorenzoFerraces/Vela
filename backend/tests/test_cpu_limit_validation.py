"""CPU limit validation: finiteness after coercion, and Docker-representable minimum."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.api.schemas import RunFromSourceRequest
from app.core.models import DeployConfig


def test_numeric_string_cpu_limit_coerces_and_passes() -> None:
    request = RunFromSourceRequest(source="nginx", cpu_limit="0.5")  # type: ignore[arg-type]
    assert request.cpu_limit == 0.5


def test_non_numeric_string_cpu_limit_is_a_validation_error() -> None:
    with pytest.raises(ValidationError):
        RunFromSourceRequest(source="nginx", cpu_limit="lots")  # type: ignore[arg-type]


def test_tiny_cpu_limit_rejected_as_unrepresentable() -> None:
    """Values below the CFS quota floor would convert to zero (unlimited) cores."""
    with pytest.raises(ValidationError):
        DeployConfig(image="nginx", cpu_limit=1e-7)
    with pytest.raises(ValidationError):
        RunFromSourceRequest(source="nginx", cpu_limit=1e-7)
