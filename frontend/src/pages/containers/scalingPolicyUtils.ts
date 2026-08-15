import type { ScalingMetric, ScalingPolicyRequest } from '../../api/client'

type ThresholdBounds = {
  min: number
  max: number | undefined
  step: number
}

export function scalingThresholdBounds(metric: ScalingMetric): ThresholdBounds {
  if (metric === 'cpu_percent') {
    return { min: 0, max: 100, step: 1 }
  }
  return { min: 0, max: undefined, step: 1 }
}

export function validateScalingPolicy(
  policy: ScalingPolicyRequest,
): string | null {
  if (policy.min_replicas > policy.max_replicas) {
    return 'Max replicas must be greater than or equal to min replicas.'
  }
  if (policy.scale_down_threshold >= policy.scale_up_threshold) {
    return 'Scale-down threshold must be lower than scale-up threshold.'
  }
  const bounds = scalingThresholdBounds(policy.metric)
  if (bounds.max !== undefined) {
    if (
      policy.scale_up_threshold > bounds.max ||
      policy.scale_down_threshold > bounds.max
    ) {
      return 'CPU percent thresholds must be 100 or less.'
    }
  }
  if (
    policy.scale_up_threshold < bounds.min ||
    policy.scale_down_threshold < bounds.min
  ) {
    return 'Scaling thresholds cannot be negative.'
  }
  return null
}
