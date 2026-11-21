from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


class ScalingPolicy(BaseModel):
    """Per-user autoscaling bounds and idle auto-stop setting."""

    user_id: str = Field(..., min_length=1)
    target_cpu_min: float = Field(..., ge=0.0, le=100.0)
    max_instances: int = Field(..., gt=0)
    min_instances: int = Field(..., ge=1)
    auto_stop_after: int | None = None

    @model_validator(mode="after")
    def min_must_be_lte_max(self) -> ScalingPolicy:
        """Reject the policy when min_instances exceeds max_instances."""
        if self.min_instances > self.max_instances:
            msg = "min_instances must be <= max_instances"
            raise ValueError(msg)
        return self
