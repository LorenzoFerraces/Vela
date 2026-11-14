import { request, VelaError } from "./client"
import type { ResolvedConfig } from "./config"
import type { ContainerInfo } from "./types"

export type Resolution =
  | { kind: "one"; container: ContainerInfo }
  | { kind: "ambiguous"; candidates: ContainerInfo[] }
  | { kind: "none" }

export function resolveContainer(
  containers: ContainerInfo[],
  query: string,
): Resolution {
  const exact = containers.filter(
    (container) => container.id === query || container.name === query,
  )
  if (exact.length === 1) return { kind: "one", container: exact[0] }
  if (exact.length > 1) return { kind: "ambiguous", candidates: exact }

  const lowered = query.toLowerCase()
  const prefixed = containers.filter(
    (container) =>
      container.id.toLowerCase().startsWith(lowered) ||
      container.name.toLowerCase().startsWith(lowered),
  )
  if (prefixed.length === 1) return { kind: "one", container: prefixed[0] }
  if (prefixed.length > 1) return { kind: "ambiguous", candidates: prefixed }
  return { kind: "none" }
}

export async function resolveContainerFromApi(
  config: ResolvedConfig & { token: string },
  query: string,
): Promise<ContainerInfo> {
  const containers = await request<ContainerInfo[]>(config, "GET", "/containers/")
  const resolution = resolveContainer(containers, query)
  if (resolution.kind === "one") return resolution.container
  if (resolution.kind === "ambiguous") {
    const names = resolution.candidates.map((container) => container.name).join(", ")
    throw new VelaError(2, `Ambiguous container "${query}": ${names}`)
  }
  throw new VelaError(404, `Container "${query}" not found.`)
}
