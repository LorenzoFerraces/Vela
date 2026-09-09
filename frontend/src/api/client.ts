/**
 * Public API surface — every symbol below is re-exported from the domain
 * modules in this directory (`./core`, `./containers`, `./stacks`, ...) so
 * existing `from '.../api/client'` imports keep working.
 */

export {
  ApiError,
  apiDelete,
  apiGet,
  apiPatch,
  apiPost,
  apiPostEmpty,
  apiPut,
  apiRequest,
  apiUploadFile,
  clearAccessToken,
  formatApiError,
  getAccessToken,
  getApiBaseUrl,
  getApiWebSocketUrl,
  getHealth,
  notifyUnauthorized,
  onUnauthorized,
  setAccessToken,
} from './core'

export {
  containerWriteAllowed,
  fetchContainerLogs,
  getContainerStats,
  getDeploySourceSuggestions,
  listContainers,
  openContainerExecWebSocket,
  openContainerLogWebSocket,
  removeContainer,
  runContainerFromSource,
  startContainer,
  stopContainer,
  uploadVolumeFolder,
  VELA_REPLICA_OF_LABEL,
} from './containers'

export { listScalingPolicies } from './scaling'

export {
  deleteDockerfileTemplate,
  createDockerfileTemplate,
  getImageAvailability,
  getImageSuggestions,
  listDockerfileTemplates,
  updateDockerfileTemplate,
} from './images'

export {
  analyzeGitSource,
  getDeploymentDiff,
  listDeployments,
} from './builds'

export {
  acceptProjectInvitation,
  cancelProjectInvitation,
  createProject,
  createProjectInvitation,
  getProjectStorageQuota,
  leaveProject,
  listIncomingInvitations,
  listProjectInvitations,
  listProjectMembers,
  listProjects,
  removeProjectMember,
  rejectProjectInvitation,
  updateProjectMemberRole,
  updateProjectStorageQuota,
} from './projects'

export {
  clerkLogin,
  deleteAvatar,
  disconnectGithub,
  getGithubAuthorizeUrl,
  getGithubStatus,
  getGithubStatusWithRetry,
  getMe,
  listGithubRepoBranches,
  listGithubRepos,
  login,
  registerUser,
  updateProfile,
  uploadAvatar,
} from './auth'

export {
  getAiPrefillPreferences,
  getGeminiConfigStatus,
  patchAiPrefillPreferences,
} from './settings'

export {
  getEmailNotificationPreferences,
  getAlertHistory,
  updateEmailNotificationPreferences,
} from './notifications'

export { exportLogs, getLogs } from './logs'

export { getAuditLog } from './audit'

export {
  getMetricPoints,
  getMetricSummary,
  getUsageSummary,
} from './metrics'

export {
  analyzeRepo,
  createStack,
  deleteStack,
  deployStack,
  getStack,
  listStacks,
  parseManifest,
  updateStack,
} from './stacks'

export type {
  ApiRequestOptions,
  HealthResponse,
  ProjectRole,
  RunSourceKind,
  VolumeMountRequest,
} from './core'

export type {
  ContainerInfo,
  ContainerLogWebSocketOptions,
  ContainerStats,
  ContainerStatus,
  DeploySourceSuggestion,
  ExecWebSocketHandle,
  PortMapping,
  RunFromSourceRequest,
  RunFromSourceResponse,
  VolumeUploadResponse,
} from './containers'

export type {
  ScalingMetric,
  ScalingPolicyInfo,
  ScalingPolicyRequest,
} from './scaling'

export type {
  DockerfileTemplate,
  ImageAvailabilityResponse,
  ImageSuggestion,
  ImageSuggestionSource,
} from './images'

export type {
  BuildOverride,
  BuildOverrideLanguage,
  DeploymentDiffResponse,
  DeploymentEnvDiff,
  DeploymentRecord,
  GitSourceAnalysis,
} from './builds'

export type {
  IncomingProjectInvitation,
  Project,
  ProjectInvitation,
  ProjectMember,
  ProjectStorageQuota,
} from './projects'

export type {
  GithubAuthorizeUrlResponse,
  GithubBranch,
  GithubRepo,
  GithubStatus,
  ListGithubReposParams,
  LoginRequest,
  RegisterRequest,
  TokenResponse,
  UserProfileUpdate,
  UserPublic,
} from './auth'

export type {
  AiPrefillPreferences,
  AiPrefillPreferencesUpdate,
} from './settings'

export type {
  AlertHistoryEntry,
  EmailNotificationPreferences,
  EmailNotificationPreferencesUpdate,
} from './notifications'

export type {
  LogEntry,
  LogQueryParams,
  LogQueryResponse,
} from './logs'

export type {
  ContainerUsageEntry,
  MetricPoint,
  MetricSummary,
  ProjectUsage,
  UsageSummary,
} from './metrics'

export type {
  AuditLogEntry,
  AuditLogQueryParams,
  AuditLogResponse,
} from './audit'

export type {
  ManifestKind,
  ManifestParseResult,
  RepoAnalysisResult,
  RepoManifestKind,
  Stack,
  StackService,
  StackServiceCreate,
} from './stacks'
