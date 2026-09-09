import {
  apiDelete,
  apiGet,
  apiPost,
  apiPut,
  type VolumeMountRequest,
} from './core'
import { type BuildOverride } from './builds'
import { type ScalingPolicyRequest } from './scaling'

export interface StackService {
  id: string
  stack_id: string
  service_name: string
  source_kind: 'image' | 'git' | 'dockerfile_template'
  source_ref: string
  git_branch: string | null
  container_port: number
  env_vars: Record<string, string>
  command: string[] | null
  public_route: boolean
  depends_on: string[] | null
  volumes: VolumeMountRequest[]
  scaling_policy: ScalingPolicyRequest | null
  build_override?: BuildOverride | null
}

export interface Stack {
  id: string
  project_id: string
  name: string
  network_name: string
  created_at: string
  services: StackService[]
  child_stack_ids: string[]
}

export interface StackServiceCreate {
  service_name: string
  source_kind: 'image' | 'git' | 'dockerfile_template'
  source_ref: string
  git_branch?: string | null
  container_port?: number
  env_vars?: Record<string, string>
  command?: string[] | null
  public_route?: boolean
  depends_on?: string[] | null
  volumes?: VolumeMountRequest[]
  scaling_policy?: ScalingPolicyRequest | null
  build_override?: BuildOverride | null
}

export async function listStacks(): Promise<Stack[]> {
  return apiGet<Stack[]>('/api/stacks/')
}

export async function createStack(body: {
  name: string
  project_id?: string
  services: StackServiceCreate[]
  child_stack_ids?: string[]
}): Promise<Stack> {
  return apiPost<Stack>('/api/stacks/', body)
}

export async function updateStack(id: string, body: {
  name: string
  project_id?: string
  services: StackServiceCreate[]
  child_stack_ids?: string[]
}): Promise<Stack> {
  return apiPut<Stack>(`/api/stacks/${encodeURIComponent(id)}`, body)
}

export type ManifestKind = 'compose' | 'k8s'

export type RepoManifestKind = 'compose' | 'k8s' | 'llm'

export interface ManifestParseResult {
  services: StackServiceCreate[]
  warnings: string[]
  manifest_kind: ManifestKind
}

export interface RepoAnalysisResult {
  services: StackServiceCreate[]
  warnings: string[]
  manifest_kind: RepoManifestKind
  manifest_path: string | null
  summary_hint: string | null
}

export async function parseManifest(body: {
  yaml_content: string
}): Promise<ManifestParseResult> {
  return apiPost<ManifestParseResult>('/api/stacks/parse-manifest', body)
}

export async function analyzeRepo(body: {
  git_url: string
  git_branch: string
}): Promise<RepoAnalysisResult> {
  return apiPost<RepoAnalysisResult>('/api/stacks/analyze-repo', body)
}

export async function getStack(id: string): Promise<Stack> {
  return apiGet<Stack>(`/api/stacks/${encodeURIComponent(id)}`)
}

export async function deleteStack(id: string): Promise<void> {
  await apiDelete(`/api/stacks/${encodeURIComponent(id)}`)
}

export async function deployStack(id: string): Promise<Record<string, unknown>> {
  return apiPost<Record<string, unknown>>(`/api/stacks/${encodeURIComponent(id)}/deploy`, {})
}
