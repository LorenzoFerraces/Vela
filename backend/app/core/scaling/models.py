from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field, model_validator


class ScalingPolicy(BaseModel):
    user_id: str = Field(..., min_length=1)
    target_cpu_min: float = Field(..., ge=0.0, le=100.0)
    max_instances: int = Field(..., gt=0)
    min_instances: int = Field(..., ge=1)
    auto_stop_after: Optional[int] = None

    @model_validator(mode="after")
    def min_must_be_lte_max(self) -> ScalingPolicy:
        if self.min_instances > self.max_instances:
            msg = "min_instances must be <= max_instances"
            raise ValueError(msg)
        return self
