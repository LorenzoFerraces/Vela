import { parseArgs } from "node:util"
import { request, requireToken, VelaError } from "../client"
import { resolveConfig } from "../config"
import { emit } from "../output"
import { formatTable } from "../format"

function rows<T>(values: T[], headers: string[], cells: (value: T) => string[]): void {
  emit(values, () => formatTable(headers, values.map(cells)))
}

export async function templatesCommand(argv: string[]): Promise<number> {
  const action = argv[0] ?? "list"
  const { positionals } = parseArgs({ args: argv.slice(1), allowPositionals: true })
  const config = requireToken(resolveConfig({}))
  if (action === "list") {
    const templates = await request<{ id: string; name: string }[]>(config, "GET", "/dockerfiles/")
    rows(templates, ["ID", "NAME"], (item) => [item.id, item.name])
    return 0
  }
  if (action === "create") {
    const [name, contents] = positionals
    if (!name || contents === undefined) throw new VelaError(2, "Usage: vela templates create <name> <contents>")
    const created = await request<{ id: string; name: string }>(config, "POST", "/dockerfiles/", { name, contents })
    emit(created, () => `Created ${created.name}`)
    return 0
  }
  if (action === "rm") {
    const id = positionals[0]
    if (!id) throw new VelaError(2, "Usage: vela templates rm <id>")
    await request<null>(config, "DELETE", `/dockerfiles/${id}`)
    emit({ removed: id }, () => `Removed ${id}`)
    return 0
  }
  throw new VelaError(2, `Unknown templates action: ${action}`)
}

export async function scaleCommand(argv: string[]): Promise<number> {
  const action = argv[0] ?? "list"
  const { positionals } = parseArgs({ args: argv.slice(1), allowPositionals: true })
  const config = requireToken(resolveConfig({}))
  if (action === "list") {
    const policies = await request<{ container_name: string; metric: string; scale_up_threshold: number }[]>(config, "GET", "/scaling/policies")
    rows(policies, ["CONTAINER", "METRIC", "SCALE UP AT"], (item) => [item.container_name, item.metric, String(item.scale_up_threshold)])
    return 0
  }
  if (action === "set") {
    const [containerName, metric, target] = positionals
    if (!containerName || !metric || target === undefined) {
      throw new VelaError(2, "Usage: vela scale set <container> <metric> <target>")
    }
    const policy = await request<{ container_name: string }>(config, "PUT", `/scaling/policies/${containerName}`, {
      metric, scale_up_threshold: Number(target), scale_down_threshold: Math.max(Number(target) / 2, 0),
    })
    emit(policy, () => `Updated ${policy.container_name}`)
    return 0
  }
  throw new VelaError(2, `Unknown scale action: ${action}`)
}

export async function metricsCommand(argv: string[]): Promise<number> {
  const action = argv[0] ?? "usage"
  const { values } = parseArgs({
    args: argv.slice(1),
    options: { container: { type: "string" }, hours: { type: "string" } },
    allowPositionals: true,
  })
  const config = requireToken(resolveConfig({}))
  if (action === "usage") {
    const usage = await request<unknown>(config, "GET", "/metrics/usage")
    emit(usage, () => JSON.stringify(usage))
    return 0
  }
  if (action === "summary") {
    if (!values.container) throw new VelaError(2, "metrics summary requires --container <name-or-id>")
    const summary = await request<unknown[]>(config, "GET", `/metrics/summary?container_id=${encodeURIComponent(values.container)}&hours=${values.hours ?? "24"}`)
    emit(summary, () => JSON.stringify(summary))
    return 0
  }
  throw new VelaError(2, `Unknown metrics action: ${action}`)
}

export async function auditCommand(argv: string[]): Promise<number> {
  const action = argv[0] ?? "list"
  const { values } = parseArgs({
    args: argv.slice(1),
    options: { global: { type: "boolean" }, limit: { type: "string" } },
    allowPositionals: true,
  })
  if (action !== "list") throw new VelaError(2, `Unknown audit action: ${action}`)
  const config = requireToken(resolveConfig({}))
  const base = values.global ? "/admin/audit" : "/audit/log"
  const limit = values.limit ?? "50"
  const result = await request<{ entries: { action: string; target_type: string; created_at: string }[]; total: number }>(
    config, "GET", `${base}?limit=${encodeURIComponent(limit)}`,
  )
  rows(result.entries, ["AT", "ACTION", "TARGET"], (entry) => [entry.created_at, entry.action, entry.target_type])
  return 0
}
