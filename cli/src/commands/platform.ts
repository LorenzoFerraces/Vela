import { parseArgs } from "node:util"
import { request, requireToken, VelaError } from "../client"
import { resolveConfig } from "../config"
import { emit } from "../output"

export async function imagesCommand(argv: string[]): Promise<number> {
  const action = argv[0] ?? "list"
  const { positionals, values } = parseArgs({
    args: argv.slice(1),
    options: { tag: { type: "string" } },
    allowPositionals: true,
  })
  const config = requireToken(resolveConfig({}))
  if (action === "list") {
    const images = await request<{ images: string[] }>(config, "GET", "/images/")
    emit(images, () => images.images.join("\n"))
    return 0
  }
  if (action === "pull") {
    const image = positionals[0]
    if (!image) throw new VelaError(2, "Usage: vela images pull <image> --tag <tag>")
    const result = await request<{ ref: string }>(config, "POST", `/images/pull?image=${encodeURIComponent(image)}&tag=${encodeURIComponent(values.tag ?? "latest")}`)
    emit(result, () => `Pulled ${result.ref}`)
    return 0
  }
  throw new VelaError(2, `Unknown images action: ${action}`)
}

export async function sourcesCommand(argv: string[]): Promise<number> {
  const action = argv[0] ?? "list"
  if (action !== "list") throw new VelaError(2, `Unknown sources action: ${action}`)
  const config = requireToken(resolveConfig({}))
  type SourceSuggestion = {
    kind: string; name?: string; id?: string; ref?: string; label?: string
    image?: string; url?: string; git_url?: string
  }
  const response = await request<{ suggestions: SourceSuggestion[] }>(config, "GET", "/containers/deploy-sources?q=")
  const describe = (suggestion: SourceSuggestion): string =>
    `${suggestion.kind}: ${suggestion.label ?? suggestion.ref ?? suggestion.name ?? suggestion.image ?? suggestion.url ?? suggestion.git_url ?? suggestion.id ?? ""}`
  emit(response, () => response.suggestions.map(describe).join("\n"))
  return 0
}

export async function settingsCommand(argv: string[]): Promise<number> {
  const action = argv[0] ?? "show"
  const config = requireToken(resolveConfig({}))
  if (action === "show") {
    const prefill = await request<unknown>(config, "GET", "/settings/ai-prefill")
    emit(prefill, () => JSON.stringify(prefill))
    return 0
  }
  if (action === "github-status") {
    return githubCommand(["status"])
  }
  if (action === "monitoring") {
    const status = await request<unknown>(config, "GET", "/settings/monitoring/status")
    emit(status, () => JSON.stringify(status))
    return 0
  }
  throw new VelaError(2, `Unknown settings action: ${action}`)
}

export async function githubCommand(argv: string[]): Promise<number> {
  const action = argv[0] ?? "status"
  if (action !== "status") throw new VelaError(2, `Unknown github action: ${action}`)
  const config = requireToken(resolveConfig({}))
  const status = await request<{ connected: boolean; login?: string; scopes: string[] }>(config, "GET", "/auth/github/status")
  emit(status, () => status.connected ? `Connected as ${status.login ?? "unknown"} (${status.scopes.join(", ")})` : "Not connected")
  return 0
}
