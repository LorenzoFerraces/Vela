#!/usr/bin/env bun
import { exitCodeFor, isVelaError, VelaError } from "./client"
import { login, logout, whoami } from "./commands/auth"
import { describe, ps } from "./commands/containers"
import { deploys, run } from "./commands/deploy"
import { exec } from "./commands/exec"
import { remove, restart, start, stop } from "./commands/lifecycle"
import { logs } from "./commands/logs"
import { tokens } from "./commands/tokens"
import { runTui } from "./tui"

const HELP = `Usage: vela <command> [options]

Commands:
  login           Log in and store a personal access token
  logout          Revoke the stored token
  whoami          Show the logged-in account
  ps              List containers
  describe <name> Show one container
  run <source>    Deploy a git URL or image
  logs <name>     Show container logs
  exec <name>     Open a shell in a container
  start|stop|restart|rm <name>
  deploys         Deployment history
  tokens <list|create|revoke>
  tui             Open the terminal UI (default with no command)
`

function isParseArgsError(error: unknown): boolean {
  if (!(error instanceof Error)) return false
  const code = (error as unknown as { code?: unknown }).code
  return typeof code === "string" && code.startsWith("ERR_PARSE_ARGS")
}

// Global --server/--token are honored anywhere before `--` by publishing
// env overrides that resolveConfig() already prefers over the stored file.
function applyGlobalConfig(argv: string[]): string[] {
  const separator = argv.indexOf("--")
  const head = separator >= 0 ? argv.slice(0, separator) : argv
  const tail = separator >= 0 ? argv.slice(separator) : []
  const rest: string[] = []
  for (let index = 0; index < head.length; index++) {
    const arg = head[index]
    if (arg === "--server" || arg === "--token") {
      const value = head[index + 1]
      if (value === undefined) {
        throw new VelaError(2, `Missing value for ${arg}.`)
      }
      if (arg === "--server") process.env.VELA_API_URL = value
      else process.env.VELA_TOKEN = value
      index++
      continue
    }
    if (arg.startsWith("--server=")) {
      process.env.VELA_API_URL = arg.slice("--server=".length)
      continue
    }
    if (arg.startsWith("--token=")) {
      process.env.VELA_TOKEN = arg.slice("--token=".length)
      continue
    }
    rest.push(arg)
  }
  return [...rest, ...tail]
}

async function main(rawArgv: string[]): Promise<number> {
  let argv: string[] = []
  try {
    argv = applyGlobalConfig(rawArgv)
  } catch (error) {
    if (isVelaError(error)) {
      console.error(error.message)
      return exitCodeFor(error)
    }
    throw error
  }
  const [command, ...rest] = argv
  try {
    switch (command) {
      case undefined:
        return await runTui()
      case "login":
        return await login(rest)
      case "logout":
        return await logout(rest)
      case "whoami":
        return await whoami(rest)
      case "ps":
        return await ps(rest)
      case "describe":
        return await describe(rest)
      case "run":
        return await run(rest)
      case "exec":
        return await exec(rest)
      case "logs":
        return await logs(rest)
      case "start":
        return await start(rest)
      case "stop":
        return await stop(rest)
      case "restart":
        return await restart(rest)
      case "rm":
        return await remove(rest)
      case "tokens":
        return await tokens(rest)
      case "deploys":
        return await deploys(rest)
      case "tui":
        return await runTui()
      default:
        console.error(`Unknown command: ${command}`)
        console.error(HELP)
        return 2
    }
  } catch (error) {
    if (isVelaError(error)) {
      console.error(error.message)
      return exitCodeFor(error)
    }
    if (isParseArgsError(error)) {
      console.error(error instanceof Error ? error.message : String(error))
      return 2
    }
    console.error(error instanceof Error ? error.message : String(error))
    if (process.env.VELA_DEBUG === "1" && error instanceof Error) {
      console.error(error.stack)
    }
    return 1
  }
}

process.exit(await main(process.argv.slice(2)))
