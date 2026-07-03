export function formatWorkloadHealth(health: string): string {
  const normalized = health.trim().toLowerCase()
  switch (normalized) {
    case 'healthy':
      return 'Healthy'
    case 'unhealthy':
      return 'Unhealthy'
    case 'starting':
      return 'Starting'
    case 'none':
    case '':
      return 'Not configured'
    default:
      return health.trim() || 'Not configured'
  }
}
