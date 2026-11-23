import { parseArgs } from "node:util"
import { request, requireToken, VelaError } from "../client"
import { resolveConfig } from "../config"
import { emit } from "../output"
import { formatTable } from "../format"

interface ProjectPublic { id: string; name: string; role?: string }
interface StackPublic { id: string; project_id: string; name: string }
interface ProjectInvitationPublic { id: string; email: string; role: string }

export async function stackCommand(argv: string[]): Promise<number> {
  const action = argv[0] ?? "list"
  const { positionals, values } = parseArgs({
    args: argv.slice(1),
    options: { project: { type: "string" } },
    allowPositionals: true,
  })
  const config = requireToken(resolveConfig({}))
  if (action === "list") {
    const stacks = await request<StackPublic[]>(config, "GET", "/stacks/")
    const project = values.project
    const rows = project ? stacks.filter((stack) => stack.project_id === project) : stacks
    emit(rows, () => formatTable(["ID", "NAME"], rows.map((stack) => [stack.id, stack.name])))
    return 0
  }
  if (action === "deploy") {
    const stackId = positionals[0]
    if (!stackId) throw new VelaError(2, "Usage: vela stack deploy <stack-id>")
    const accepted = await request<{ job_id: string }>(config, "POST", `/stacks/${stackId}/deploy`)
    emit(accepted, () => `Deploy job: ${accepted.job_id}`)
    return 0
  }
  if (action === "rm") {
    const stackId = positionals[0]
    if (!stackId) throw new VelaError(2, "Usage: vela stack rm <stack-id>")
    await request<null>(config, "DELETE", `/stacks/${stackId}`)
    emit({ removed: stackId }, () => `Removed ${stackId}`)
    return 0
  }
  throw new VelaError(2, `Unknown stack action: ${action}`)
}

export async function projectsCommand(argv: string[]): Promise<number> {
  const action = argv[0] ?? "list"
  const { positionals } = parseArgs({ args: argv.slice(1), allowPositionals: true })
  const config = requireToken(resolveConfig({}))
  if (action === "list") {
    const projects = await request<ProjectPublic[]>(config, "GET", "/projects/")
    emit(projects, () => formatTable(["ID", "NAME", "ROLE"], projects.map((project) => [project.id, project.name, project.role ?? ""])))
    return 0
  }
  if (action === "create") {
    const name = positionals[0]
    if (!name) throw new VelaError(2, "Usage: vela projects create <name>")
    const created = await request<ProjectPublic>(config, "POST", "/projects/", { name })
    emit(created, () => `Created ${created.name} (${created.id})`)
    return 0
  }
  throw new VelaError(2, `Unknown projects action: ${action}`)
}

export async function teamsCommand(argv: string[]): Promise<number> {
  return projectsCommand(argv)
}

export async function inviteCommand(argv: string[]): Promise<number> {
  const action = argv[0] ?? "list"
  const { positionals, values } = parseArgs({
    args: argv.slice(1),
    options: { project: { type: "string" } },
    allowPositionals: true,
  })
  if (!values.project) throw new VelaError(2, "invite requires --project <id>")
  const config = requireToken(resolveConfig({}))
  if (action === "list") {
    const invites = await request<ProjectInvitationPublic[]>(config, "GET", `/projects/${values.project}/invitations`)
    emit(invites, () => formatTable(["ID", "EMAIL", "ROLE"], invites.map((invite) => [invite.id, invite.email, invite.role])))
    return 0
  }
  if (action === "create") {
    const [email, role] = positionals
    if (!email || !role) throw new VelaError(2, "Usage: vela invite create <email> <operator|viewer> --project <id>")
    if (role !== "operator" && role !== "viewer") throw new VelaError(2, "role must be operator or viewer")
    const created = await request<ProjectInvitationPublic>(config, "POST", `/projects/${values.project}/invitations`, { email, role })
    emit(created, () => `Invited ${created.email}`)
    return 0
  }
  if (action === "cancel") {
    const id = positionals[0]
    if (!id) throw new VelaError(2, "Usage: vela invite cancel <invitation-id> --project <id>")
    await request<null>(config, "DELETE", `/projects/${values.project}/invitations/${id}`)
    emit({ cancelled: id }, () => `Cancelled ${id}`)
    return 0
  }
  throw new VelaError(2, `Unknown invite action: ${action}`)
}
