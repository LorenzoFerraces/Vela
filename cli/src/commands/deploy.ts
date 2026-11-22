import { parseArgs } from "node:util"

import { request, requireToken, VelaError } from "../client"
import { resolveConfig } from "../config"
import { formatTable } from "../format"
import { emit } from "../output"
import type { DeploymentRecord, DeployJob } from "../types"

interface RunAccepted {
  job_id: string
  status: "in_progress"
}

function isGitSource(source: string): boolean {
  return (
    source.startsWith("git@") ||
    source.startsWith("http://") ||
    source.startsWith("https://") ||
    source.startsWith("ssh://")
  )
}

export function parseEnv(values: string[] | undefined): Record<string, string> {
  const env: Record<string, string> = {}
  for (const entry of values ?? []) {
    const separator = entry.indexOf("=")
    if (separator < 1) {
      throw new VelaError(2, `Invalid --env value "${entry}". Use KEY=VALUE.`)
    }
    env[entry.slice(0, separator)] = entry.slice(separator + 1)
  }
  return env
}

interface WaitOptions {
  maxAttempts?: number
  poll?: (config: { server: string; token: string }) => Promise<DeployJob[]>
}

export async function waitForJob(
  config: { server: string; token: string },
  jobId: string,
  options: WaitOptions = {},
): Promise<DeployJob> {
  const maxAttempts = options.maxAttempts ?? 600
  const poll = options.poll ?? ((cfg) => request<DeployJob[]>(cfg, "GET", "/deploys/active"))
  let lastPhase = ""
  for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
    const jobs = await poll(config)
    const job = jobs.find((candidate) => candidate.job_id === jobId)
    if (!job) {
      throw new VelaError(1, "Deploy job disappeared before completing.")
    }
    if (job.phase !== lastPhase) {
      const detail = job.phase_detail ? ` ${job.phase_detail}` : ""
      console.log(`[${job.phase}]${detail}`)
      lastPhase = job.phase
    }
    if (job.status === "succeeded") return job
    if (job.status === "failed") {
      throw new VelaError(1, job.error?.detail ?? "Deploy failed.")
    }
    await Bun.sleep(1000)
  }
  throw new VelaError(1, "Deploy job did not complete in time.")
}

export async function run(argv: string[]): Promise<number> {
  const { values, positionals } = parseArgs({
    args: argv,
    options: {
      name: { type: "string" },
      port: { type: "string" },
      env: { type: "string", multiple: true },
      public: { type: "boolean" },
      branch: { type: "string" },
      template: { type: "string" },
      project: { type: "string" },
      "no-wait": { type: "boolean" },
    },
    allowPositionals: true,
  })
  const source = positionals[0]
  if (!source) {
    console.error("Usage: vela run <git-url|image> [--port 80] [--env K=V] [--public]")
    return 2
  }

  const port = values.port ? Number(values.port) : undefined
  if (port !== undefined && (!Number.isInteger(port) || port < 1 || port > 65535)) {
    throw new VelaError(2, `Invalid --port "${values.port}".`)
  }

  const body: Record<string, unknown> = {
    container_name: values.name,
    container_port: port,
    env_vars: parseEnv(values.env),
    public_route: values.public ?? false,
    project_id: values.project,
  }

  if (values.template) {
    body.source_kind = "dockerfile_template"
    body.dockerfile_template_id = values.template
  } else if (isGitSource(source)) {
    body.source_kind = "git"
    body.git_url = source
    body.git_branch = values.branch ?? "main"
  } else {
    body.source_kind = "image"
    body.image_ref = source
  }

  const config = requireToken(resolveConfig({}))
  const accepted = await request<RunAccepted>(config, "POST", "/containers/run", body)
  console.log(`Queued deploy ${accepted.job_id}.`)
  if (values["no-wait"]) {
    console.log(accepted.job_id)
    return 0
  }
  const job = await waitForJob(config, accepted.job_id)

  emit(job, () => {
    let text = `Deployed ${job.name}.`
    const result =
      typeof job.result === "object" && job.result !== null
        ? (job.result as Record<string, unknown>)
        : null
    const urlCandidates = [
      result?.access_url,
      result?.public_url,
      result?.url,
      (result?.container as Record<string, unknown> | undefined)?.access_url,
      (result?.container as Record<string, unknown> | undefined)?.public_url,
    ]
    for (const candidate of urlCandidates) {
      if (typeof candidate === "string" && candidate) {
        text += `\n${candidate}`
        break
      }
    }
    return text
  })
  return 0
}

export async function deploys(argv: string[]): Promise<number> {
  parseArgs({ args: argv, options: {}, allowPositionals: false })
  const config = requireToken(resolveConfig({}))
  const records = await request<DeploymentRecord[]>(config, "GET", "/deployments/")
  emit(records, () => {
    const rows = records.map((record) => [
      record.container_name ?? record.image_tag,
      record.source_kind,
      record.source_ref,
      record.git_branch ?? "",
      record.public_url ?? "",
      record.created_at,
    ])
    return formatTable(["NAME", "SOURCE", "REF", "BRANCH", "URL", "CREATED"], rows)
  })
  return 0
}
