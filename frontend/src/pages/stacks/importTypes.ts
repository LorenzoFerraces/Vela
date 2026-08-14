import type { StackServiceCreate } from '../../api/client'

export type ImportedStackState = {
  importedStack: { name: string; services: StackServiceCreate[] }
  composeWarnings: string[]
}
