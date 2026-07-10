from typing import Optional

from pydantic import BaseModel, Field


class ScalingPolicy(BaseModel):
    user_id: str = Field(..., min_length=1)
    target_cpu_min: float = Field(..., ge=0.0, le=100.0)
    max_instances: int = Field(..., gt=0)
    min_instances: int = Field(..., ge=1, le=max_instances)
    auto_stop_after: Optional[int] = None
