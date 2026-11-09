import { parseArgs } from "node:util"

import { request, requireToken, VelaError } from "../client"
import { resolveConfig } from "../config"
import { formatTable } from "../format"
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

function parseEnv(values: string[] | undefined): Record<string, string> {
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

export async function waitForJob(
  config: { server: string; token: string },
  jobId: string,
): Promise<DeployJob> {
  let lastPhase = ""
  for (;;) {
    const jobs = await request<DeployJob[]>(config, "GET", "/deploys/active")
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
      json: { type: "boolean" },
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
  const job = await waitForJob(config, accepted.job_id)

  if (values.json) {
    console.log(JSON.stringify(job, null, 2))
    return 0
  }
  console.log(`Deployed ${job.name}.`)
  const result = job.result
  if (typeof result === "object" && result !== null && "access_url" in result) {
    const url = (result as Record<string, unknown>).access_url
    if (typeof url === "string") console.log(url)
  }
  return 0
}

export async function deploys(argv: string[]): Promise<number> {
  const { values } = parseArgs({
    args: argv,
    options: { json: { type: "boolean" } },
    allowPositionals: false,
  })
  const config = requireToken(resolveConfig({}))
  const records = await request<DeploymentRecord[]>(config, "GET", "/deployments/")
  if (values.json) {
    console.log(JSON.stringify(records, null, 2))
    return 0
  }
  const rows = records.map((record) => [
    record.container_name ?? record.image_tag,
    record.source_kind,
    record.source_ref,
    record.git_branch ?? "",
    record.public_url ?? "",
    record.created_at,
  ])
  console.log(
    formatTable(["NAME", "SOURCE", "REF", "BRANCH", "URL", "CREATED"], rows),
  )
  return 0
}
