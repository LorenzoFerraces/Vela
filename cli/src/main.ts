#!/usr/bin/env bun
import { exitCodeFor, isVelaError } from "./client"
import { login, logout, whoami } from "./commands/auth"
import { describe, ps } from "./commands/containers"

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

async function main(argv: string[]): Promise<number> {
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
    console.error(error instanceof Error ? error.message : String(error))
    if (process.env.VELA_DEBUG === "1" && error instanceof Error) {
      console.error(error.stack)
    }
    return 1
  }
}

async function runTui(): Promise<number> {
  // ponytail: stub until Task 11 wires the real TUI; exits 1 listing commands.
  console.error("The TUI is not wired up yet.")
  console.error(HELP)
  return 1
}

process.exit(await main(process.argv.slice(2)))
