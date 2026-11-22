import { VelaError } from "../client"

const COMMANDS = [
  "login", "logout", "whoami", "run", "ps", "describe", "exec", "logs",
  "start", "stop", "restart", "rm", "tokens", "deploys", "stack", "projects",
  "teams", "invite", "templates", "scale", "metrics", "audit", "images",
  "sources", "settings", "github", "config", "completion", "tui",
]

export async function completionCommand(argv: string[]): Promise<number> {
  const shell = argv[0]
  if (shell !== "bash" && shell !== "zsh" && shell !== "fish" && shell !== "powershell") {
    throw new VelaError(2, "Usage: vela completion <bash|zsh|fish|powershell>")
  }
  const words = COMMANDS.join(" ")
  if (shell === "bash") {
    console.log(`_vela() { COMPREPLY=( $(compgen -W "${words}" -- "\${COMP_WORDS[COMP_CWORD]}") ); }\ncomplete -F _vela vela`)
  } else if (shell === "zsh") {
    console.log(`#compdef vela\n_arguments '1: :(${words})'`)
  } else if (shell === "fish") {
    console.log(`complete -c vela -f -a '${words}'`)
  } else {
    console.log(`Register-ArgumentCompleter -Native -CommandName vela -ScriptBlock {\n  param($wordToComplete)\n  @(${COMMANDS.map((name) => `'${name}'`).join(", ")}) | Where-Object { $_ -like "$wordToComplete*" }\n}`)
  }
  return 0
}
