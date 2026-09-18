import { apiGet } from './core'

export interface MetricPoint {
  timestamp: string
  cpu_percent: number
  memory_usage_bytes: number
  memory_limit_bytes: number
  memory_percent: number
  network_rx_bytes: number
  network_tx_bytes: number
}

export interface MetricSummary {
  bucket_start: string
  cpu_avg: number
  cpu_max: number
  cpu_min: number
  memory_usage_avg: number
  memory_usage_max: number
  memory_limit_avg: number
  memory_percent_avg: number
  memory_percent_max: number
  network_rx_total: number
  network_tx_total: number
}

export async function getMetricPoints(
  containerId: string,
  options: { hours?: number; limit?: number } = {}
): Promise<MetricPoint[]> {
  const params = new URLSearchParams({ container_id: containerId })
  if (options.hours != null) params.set('hours', String(options.hours))
  if (options.limit != null) params.set('limit', String(options.limit))
  return apiGet<MetricPoint[]>(`/api/metrics?${params.toString()}`)
}

export async function getMetricSummary(
  containerId: string,
  hours: number = 24
): Promise<MetricSummary[]> {
  const params = new URLSearchParams({
    container_id: containerId,
    hours: String(hours),
  })
  return apiGet<MetricSummary[]>(`/api/metrics/summary?${params.toString()}`)
}

export interface ContainerUsageEntry {
  container_id: string
  name: string
  status: string
  project_id: string | null
  project_name: string | null
  team_name: string | null
  cpu_percent: number | null
  memory_usage_bytes: number | null
  memory_percent: number | null
}

export interface ProjectUsage {
  project_id: string | null
  project_name: string | null
  team_name: string | null
  cpu_percent_total: number
  memory_usage_bytes_total: number
  storage_quota_bytes: number | null
  storage_used_bytes: number
  storage_over_quota: boolean
  containers: ContainerUsageEntry[]
}

export interface UsageSummary {
  projects: ProjectUsage[]
  total_cpu_percent: number
  total_memory_usage_bytes: number
  running_containers: number
}

export async function getUsageSummary(): Promise<UsageSummary> {
  return apiGet<UsageSummary>('/api/metrics/usage')
}
