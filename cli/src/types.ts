export interface PortMapping {
  host_port: number
  container_port: number
  protocol: string
}

export interface ContainerInfo {
  id: string
  name: string
  image: string
  status: string
  health: string
  ports: PortMapping[]
  labels: Record<string, string>
  access_url: string | null
  access_role: string | null
  source_kind: string | null
  source_label: string | null
  created_at: string
}

export interface ContainerStats {
  container_id: string
  timestamp: string
  cpu_percent: number
  memory_usage_bytes: number
  memory_limit_bytes: number
  memory_percent: number
  network_rx_bytes: number
  network_tx_bytes: number
}

export interface DeployJob {
  job_id: string
  kind: "container" | "stack"
  project_id: string
  name: string
  source_label: string
  status: "in_progress" | "succeeded" | "failed"
  phase: string
  phase_detail: string | null
  services: { name: string; state: string }[]
  error: { code?: string; detail?: string } | null
  result: unknown
  created_at: string
  finished_at: string | null
}

export interface DeploymentRecord {
  id: string
  container_name: string | null
  source_kind: string
  source_ref: string
  git_branch: string | null
  image_tag: string
  container_port: number
  public_url: string | null
  created_at: string
}
