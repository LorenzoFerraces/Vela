import { apiGet } from './core'

export type ScalingMetric = 'cpu_percent' | 'requests_per_second'

export interface ScalingPolicyRequest {
  enabled: boolean
  min_replicas: number
  max_replicas: number
  metric: ScalingMetric
  scale_up_threshold: number
  scale_down_threshold: number
  cooldown_seconds: number
  scale_up_stabilization_seconds: number
  scale_down_stabilization_seconds: number
}

export interface ScalingPolicyInfo {
  id: string
  container_name: string
  enabled: boolean
  min_replicas: number
  max_replicas: number
  metric: ScalingMetric
  scale_up_threshold: number
  scale_down_threshold: number
  cooldown_seconds: number
  scale_up_stabilization_seconds: number
  scale_down_stabilization_seconds: number
  last_scaled_at: string | null
  created_at: string
  updated_at: string
}

export async function listScalingPolicies(): Promise<ScalingPolicyInfo[]> {
  return apiGet<ScalingPolicyInfo[]>('/api/scaling/policies', { cache: true })
}
