import type { ResolvedConfig } from "./config"

export class VelaError extends Error {
  readonly velaError = true

  constructor(
    readonly status: number,
    message: string,
    readonly code?: string,
  ) {
    super(message)
    this.name = "VelaError"
  }
}

export function isVelaError(value: unknown): value is VelaError {
  return typeof value === "object" && value !== null && "velaError" in value
}

export function toVelaError(
  status: number,
  payload: unknown,
  fallback: string,
): VelaError {
  let detail = fallback
  let code: string | undefined
  if (typeof payload === "object" && payload !== null) {
    const record = payload as Record<string, unknown>
    if (typeof record.detail === "string") detail = record.detail
    else if (Array.isArray(record.detail)) {
      const parts = record.detail
        .filter(
          (entry): entry is { msg: string; loc?: unknown } =>
            typeof entry === "object" &&
            entry !== null &&
            typeof (entry as { msg?: unknown }).msg === "string",
        )
        .map((entry) => {
          const loc = Array.isArray(entry.loc)
            ? entry.loc.map(String).join(".")
            : ""
          return loc ? `${loc}: ${entry.msg}` : entry.msg
        })
      if (parts.length > 0) detail = parts.join("; ")
    }
    if (typeof record.code === "string") code = record.code
  }
  return new VelaError(status, detail, code)
}

export function exitCodeFor(error: VelaError): number {
  if (error.status === 401 || error.status === 403) return 3
  if (error.status === 404) return 4
  if (error.status === 400 || error.status === 422 || error.status === 2) return 2
  return 1
}

export function requireToken(
  config: ResolvedConfig,
): ResolvedConfig & { token: string } {
  if (!config.token) {
    throw new VelaError(401, "Not authenticated. Run `vela login`.")
  }
  return { ...config, token: config.token }
}

export async function request<T>(
  config: Pick<ResolvedConfig, "server" | "token">,
  method: string,
  path: string,
  body?: unknown,
): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" }
  if (config.token) headers.Authorization = `Bearer ${config.token}`
  if (body !== undefined) headers["Content-Type"] = "application/json"

  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), 30_000)
  let response: Response
  try {
    response = await fetch(`${config.server}/api${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal,
    })
  } catch (error) {
    clearTimeout(timeout)
    if (error instanceof Error && error.name === "AbortError") {
      throw new VelaError(0, `Request to ${config.server} timed out.`)
    }
    throw new VelaError(0, `Cannot reach ${config.server}. Is the API running?`)
  }
  clearTimeout(timeout)

  const text = await response.text()
  let payload: unknown = null
  if (text) {
    try {
      payload = JSON.parse(text)
    } catch {
      payload = null
    }
  }
  if (!response.ok) {
    throw toVelaError(response.status, payload, `Request failed (${response.status}).`)
  }
  return payload as T
}
