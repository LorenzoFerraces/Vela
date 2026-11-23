# Group D — CLI (F11 + F07) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the CLI named server profiles, completions and uniform scriptable output, and expose the existing backend surface as commands.

**Architecture:** CLI-only changes in `cli/`. Config stays a single JSON file that migrates from the legacy flat shape to a profile map on first read; `resolveConfig()` keeps its existing 3-argument shape so all 11 call sites keep working. Global flags (`--profile`, `--json`, `--quiet`) are normalised in `applyGlobalConfig()` in `main.ts` into env vars, which every command reads, avoiding parser changes in each command. New commands are thin `request()` wrappers around existing REST endpoints; backend 403s are surfaced through the existing `toVelaError`/`exitCodeFor` rather than re-implementing role checks in the CLI.

**Tech Stack:** Bun + TypeScript, `node:util` `parseArgs`, existing `cli/src/client.ts` request helper, `bun:test`.

## Global Constraints

- Worktree root: `C:\Users\lolo\.local\share\opencode\worktree\ab1b01\defect-remediation`. All paths below are relative to it.
- `cli/package.json` dependencies stay exact-pinned; no new dependency may be added for profiles, output or completions.
- Keep the `request()` path convention: pass paths starting with `/` (e.g. `/stacks/`); `request()` prepends `/api`.
- Keep config file permissions at `0o600` (best-effort on Windows) and treat a corrupt config file as absent (`null`).
- Never print a stored token in plaintext from `vela config get`.
- `run --no-wait` already exists (`cli/src/commands/deploy.ts`); do not change its behaviour.
- Verify after each task: `cd cli && bun test && bun run typecheck`. Final gate also `bun run build`.

---

### Task 1: F11 — profile-aware config with legacy migration

**Files:**
- Modify: `cli/src/config.ts`
- Test: `cli/src/config.test.ts`

**Interfaces:**
- Consumes: `DEFAULT_SERVER`, `configPath(env)`, existing `StoredConfig` flat shape.
- Produces: `ConfigProfile { server: string; token: string; tokenId?: string }`; `StoredConfig { profiles: Record<string, ConfigProfile>; active: string }`; `ResolvedConfig { server: string; token?: string; tokenId?: string; profile: string }`; `resolveConfig(flags: { server?: string; token?: string; profile?: string }, env?, stored?)`; `readStoredConfig(path?)`, `writeStoredConfig(config, path?)`, `clearStoredConfig(path?)` unchanged in name.

- [ ] **Step 1: Write failing migration and profile-selection tests** in `cli/src/config.test.ts`

```ts
import { describe, expect, test, beforeEach, afterEach } from "bun:test"
import { mkdtempSync, rmSync, readFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { configPath, readStoredConfig, writeStoredConfig, resolveConfig } from "./config"

let directory: string
let configFile: string
beforeEach(() => { directory = mkdtempSync(join(tmpdir(), "vela-config-")); configFile = join(directory, "config.json") })
afterEach(() => { rmSync(directory, { recursive: true, force: true }) })

test("migrates a legacy flat config into the default profile once", () => {
  writeFileSync(configFile, JSON.stringify({ server: "http://old:8000", token: "pat_old", tokenId: "tid_1" }))
  const stored = readStoredConfig(configFile)
  expect(stored).toEqual({ profiles: { default: { server: "http://old:8000", token: "pat_old", tokenId: "tid_1" } }, active: "default" })
  expect(JSON.parse(readFileSync(configFile, "utf8")).profiles.default.token).toBe("pat_old")
})

test("VELA_PROFILE selects a named profile and env overrides still win", () => {
  writeStoredConfig({ profiles: {
    default: { server: "http://default:8000", token: "pat_default" },
    school: { server: "http://school:8000/", token: "pat_school", tokenId: "tid_school" },
  }, active: "default" }, configFile)
  const resolved = resolveConfig({}, { VELA_PROFILE: "school", VELA_API_URL: "http://override:9000" }, readStoredConfig(configFile)!)
  expect(resolved).toEqual({ server: "http://override:9000", token: "pat_school", tokenId: "tid_school", profile: "school" })
})

test("flags.profile overrides the active profile and keeps its tokenId", () => {
  writeStoredConfig({ profiles: {
    default: { server: "http://default:8000", token: "pat_default" },
    school: { server: "http://school:8000", token: "pat_school", tokenId: "tid_school" },
  }, active: "default" }, configFile)
  expect(resolveConfig({ profile: "school" }, {}, readStoredConfig(configFile)!))
    .toEqual({ server: "http://school:8000", token: "pat_school", tokenId: "tid_school", profile: "school" })
})

test("unknown profile falls back to active and a corrupt file is still null", () => {
  writeStoredConfig({ profiles: { default: { server: "http://d:8000", token: "t" } }, active: "default" }, configFile)
  expect(resolveConfig({ profile: "missing" }, {}, readStoredConfig(configFile)!).profile).toBe("default")
  writeFileSync(configFile, "{not json")
  expect(readStoredConfig(configFile)).toBeNull()
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd cli && bun test src/config.test.ts`
Expected: FAIL — `StoredConfig` has no `profiles`, `resolveConfig` ignores `profile`.

- [ ] **Step 3: Replace `cli/src/config.ts` declarations and implementations** with the profile-aware version (keep `DEFAULT_SERVER`, `configPath`, write/clear behaviour):

```ts
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync, chmodSync } from "node:fs"
import { dirname, join } from "node:path"
import { homedir } from "node:os"

export const DEFAULT_SERVER = "http://127.0.0.1:8000"
const DEFAULT_PROFILE = "default"

interface LegacyConfig { server?: unknown; token?: unknown; tokenId?: unknown }
export interface ConfigProfile { server: string; token: string; tokenId?: string }
export interface StoredConfig { profiles: Record<string, ConfigProfile>; active: string }
export interface ResolvedConfig { server: string; token?: string; tokenId?: string; profile: string }

export function configPath(env: NodeJS.ProcessEnv = process.env): string {
  return env.VELA_CONFIG ?? join(homedir(), ".vela", "config.json")
}

function readProfile(value: unknown): ConfigProfile | null {
  if (!value || typeof value !== "object") return null
  const candidate = value as Record<string, unknown>
  if (typeof candidate.server !== "string" || typeof candidate.token !== "string") return null
  return {
    server: candidate.server,
    token: candidate.token,
    ...(typeof candidate.tokenId === "string" ? { tokenId: candidate.tokenId } : {}),
  }
}

export function readStoredConfig(path: string = configPath()): StoredConfig | null {
  try {
    if (!existsSync(path)) return null
    const parsed = JSON.parse(readFileSync(path, "utf8")) as Record<string, unknown>
    if (parsed.profiles && typeof parsed.profiles === "object") {
      const profiles: Record<string, ConfigProfile> = {}
      for (const [name, value] of Object.entries(parsed.profiles as Record<string, unknown>)) {
        const profile = readProfile(value)
        if (profile) profiles[name] = profile
      }
      if (!Object.keys(profiles).length) return null
      const active = typeof parsed.active === "string" && profiles[parsed.active]
        ? parsed.active
        : Object.keys(profiles)[0]
      return { profiles, active }
    }
    const legacy = parsed as LegacyConfig
    if (typeof legacy.server === "string" && typeof legacy.token === "string") {
      const migrated: StoredConfig = {
        profiles: { [DEFAULT_PROFILE]: {
          server: legacy.server, token: legacy.token,
          ...(typeof legacy.tokenId === "string" ? { tokenId: legacy.tokenId } : {}),
        } },
        active: DEFAULT_PROFILE,
      }
      writeStoredConfig(migrated, path)
      return migrated
    }
    return null
  } catch { return null }
}

export function writeStoredConfig(config: StoredConfig, path: string = configPath()): void {
  mkdirSync(dirname(path), { recursive: true })
  writeFileSync(path, JSON.stringify(config, null, 2) + "\n", { mode: 0o600 })
  try { chmodSync(path, 0o600) } catch { /* Windows: mode is advisory, ACLs govern access. */ }
}

export function clearStoredConfig(path: string = configPath()): void {
  rmSync(path, { force: true })
}

export function resolveConfig(
  flags: { server?: string; token?: string; profile?: string },
  env: NodeJS.ProcessEnv = process.env,
  stored: StoredConfig | null = readStoredConfig(),
): ResolvedConfig {
  const profileName = flags.profile ?? env.VELA_PROFILE ?? stored?.active ?? DEFAULT_PROFILE
  const profile = stored?.profiles[profileName] ?? stored?.profiles[stored.active] ?? null
  const server = (flags.server ?? env.VELA_API_URL ?? profile?.server ?? DEFAULT_SERVER).replace(/\/+$/, "")
  const fromOverride = flags.token !== undefined || env.VELA_TOKEN !== undefined
  return {
    server,
    token: flags.token ?? env.VELA_TOKEN ?? profile?.token,
    tokenId: fromOverride ? undefined : profile?.tokenId,
    profile: profile?.server ? profileName : (stored?.active ?? DEFAULT_PROFILE),
  }
}
```

- [ ] **Step 4: Update existing callers that construct `StoredConfig` literals**

`cli/src/commands/auth.ts` `login()` currently calls `writeStoredConfig({ server, token, tokenId })`. Change it to preserve the active profile:

```ts
const stored = readStoredConfig()
const active = stored?.active ?? "default"
const profiles = stored?.profiles ?? {}
writeStoredConfig({
  profiles: { ...profiles, [active]: { server, token, tokenId } },
  active,
})
```

Add `readStoredConfig` to the existing import from `../config`. `logout()` keeps `clearStoredConfig()`; update `cli/README.md` only in Task 8.

Also fix the server fallback in `login()` (auth.ts:38), which still reads `stored?.server` from the legacy flat shape and no longer typechecks against the profile-shaped `StoredConfig`:

```ts
const stored = readStoredConfig()
const activeProfile = stored?.profiles[stored.active]
const server = (values.server ?? process.env.VELA_API_URL ?? activeProfile?.server ?? DEFAULT_SERVER)
  .replace(/\/+$/, "")
```

- [ ] **Step 5: Run tests and typecheck**

Run: `cd cli && bun test && bun run typecheck`
Expected: PASS (TUI `resolveConfig({})` still compiles because `profile` is optional).

- [ ] **Step 6: Commit**

```bash
git add cli/src/config.ts cli/src/config.test.ts cli/src/commands/auth.ts
git commit -m "feat(cli): add named config profiles with legacy migration"
```

---

### Task 2: F11 — `vela config` command and global `--profile`

**Files:**
- Modify: `cli/src/main.ts`
- Create: `cli/src/commands/config.ts`
- Test: `cli/src/commands/config.test.ts`

**Interfaces:**
- Consumes: `readStoredConfig`, `writeStoredConfig`, `resolveConfig` from Task 1.
- Produces: `configCommand(argv: string[]): Promise<number>`; global flag `--profile` published as `VELA_PROFILE`.

- [ ] **Step 1: Write failing tests** in `cli/src/commands/config.test.ts` using a temp config path and `VELA_CONFIG` env save/restore:

```ts
import { describe, expect, test, beforeEach, afterEach } from "bun:test"
import { mkdtempSync, rmSync, readFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { configCommand } from "./config"

let directory: string
let configFile: string
const savedEnv = process.env.VELA_CONFIG
beforeEach(() => {
  directory = mkdtempSync(join(tmpdir(), "vela-config-"))
  configFile = join(directory, "config.json")
  process.env.VELA_CONFIG = configFile
})
afterEach(() => {
  if (savedEnv === undefined) delete process.env.VELA_CONFIG; else process.env.VELA_CONFIG = savedEnv
  rmSync(directory, { recursive: true, force: true })
})

test("config use switches the active profile", async () => {
  const { writeStoredConfig } = await import("../config")
  writeStoredConfig({ profiles: {
    default: { server: "http://d:8000", token: "t1" },
    school: { server: "http://s:8000", token: "t2" },
  }, active: "default" })
  const output: string[] = []
  const log = console.log; console.log = (value: string) => output.push(value)
  try { expect(await configCommand(["use", "school"])).toBe(0) } finally { console.log = log }
  expect(JSON.parse(readFileSync(configFile, "utf8")).active).toBe("school")
  expect(output.join(" ")).toContain("school")
})

test("config get never prints the token", async () => {
  const { writeStoredConfig } = await import("../config")
  writeStoredConfig({ profiles: { default: { server: "http://d:8000", token: "super-secret" } }, active: "default" })
  const output: string[] = []
  const log = console.log; console.log = (value: string) => output.push(value)
  try { expect(await configCommand(["get", "token"])).toBe(0) } finally { console.log = log }
  expect(output.join(" ")).not.toContain("super-secret")
  expect(output.join(" ")).toContain("<set>")
})

test("config set creates a profile and config list names it", async () => {
  expect(await configCommand(["set", "server", "http://new:8000", "--profile", "lab"])).toBe(0)
  expect(await configCommand(["list"])).toBe(0)
  const stored = JSON.parse(readFileSync(configFile, "utf8"))
  expect(stored.profiles.lab.server).toBe("http://new:8000")
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd cli && bun test src/commands/config.test.ts`
Expected: FAIL — cannot resolve `./config`.

- [ ] **Step 3: Create `cli/src/commands/config.ts`**

```ts
import { parseArgs } from "node:util"
import { readStoredConfig, writeStoredConfig, clearStoredConfig, configPath } from "../config"
import { VelaError } from "../client"

export async function configCommand(argv: string[]): Promise<number> {
  const action = argv[0] ?? "list"
  const { values, positionals } = parseArgs({
    args: argv.slice(1),
    options: { profile: { type: "string" } },
    allowPositionals: true,
  })
  const path = configPath()
  const stored = readStoredConfig(path) ?? { profiles: {}, active: "default" }
  const profileName = values.profile ?? stored.active

  if (action === "list") {
    for (const [name, profile] of Object.entries(stored.profiles)) {
      console.log(`${name === stored.active ? "*" : " "} ${name}  ${profile.server}`)
    }
    return 0
  }
  if (action === "use") {
    const name = positionals[0]
    if (!name || !stored.profiles[name]) throw new VelaError(2, `Unknown profile: ${name ?? "(none)"}`)
    writeStoredConfig({ ...stored, active: name }, path)
    console.log(`Active profile: ${name}`)
    return 0
  }
  if (action === "get") {
    const key = positionals[0]
    const profile = stored.profiles[profileName]
    if (!profile) throw new VelaError(2, `Unknown profile: ${profileName}`)
    if (!key || key === "server") { console.log(profile.server); return 0 }
    if (key === "token") { console.log(profile.token ? "<set>" : "<unset>"); return 0 }
    if (key === "tokenId") { console.log(profile.tokenId ?? "<unset>"); return 0 }
    if (key === "active") { console.log(stored.active); return 0 }
    throw new VelaError(2, `Unknown key: ${key}`)
  }
  if (action === "set") {
    const key = positionals[0]
    const value = positionals[1]
    if (!key || value === undefined) throw new VelaError(2, "Usage: vela config set <server|token> <value> [--profile <name>]")
    if (key !== "server" && key !== "token") throw new VelaError(2, `Unknown key: ${key}`)
    const current = stored.profiles[profileName] ?? { server: "", token: "" }
    const next = { ...current, [key]: value }
    if (key === "token") delete next.tokenId
    writeStoredConfig({ profiles: { ...stored.profiles, [profileName]: next }, active: stored.active }, path)
    console.log(`Updated ${key} in profile ${profileName}`)
    return 0
  }
  if (action === "clear") {
    clearStoredConfig(path)
    console.log("Config removed")
    return 0
  }
  throw new VelaError(2, `Unknown config action: ${action}`)
}
```

- [ ] **Step 4: Wire `--profile` and `config` into `cli/src/main.ts`**

In `applyGlobalConfig`, extend the recognised flags alongside `--server`/`--token` (handle both `--profile value` and `--profile=value`):

```ts
if (arg === "--profile" && index + 1 < head.length) {
  process.env.VELA_PROFILE = head[index + 1]; index += 2; continue
}
if (arg.startsWith("--profile=")) {
  process.env.VELA_PROFILE = arg.slice("--profile=".length); index += 1; continue
}
```

Update `HELP` to list `--profile <name>` and the `config` command. Add to the `switch`:

```ts
case "config": return await configCommand(rest)
```

and import `configCommand` from `./commands/config`.

- [ ] **Step 5: Run tests and typecheck**

Run: `cd cli && bun test && bun run typecheck`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add cli/src/main.ts cli/src/commands/config.ts cli/src/commands/config.test.ts
git commit -m "feat(cli): add vela config command and --profile flag"
```

---

### Task 3: uniform `--json` / `--quiet` output

**Files:**
- Create: `cli/src/output.ts`
- Modify: `cli/src/main.ts`, `cli/src/commands/deploy.ts`, `cli/src/commands/containers.ts`, `cli/src/commands/tokens.ts`, `cli/src/commands/auth.ts`
- Test: `cli/src/output.test.ts`

**Interfaces:**
- Consumes: global flags from Task 2's normalisation mechanism.
- Produces: `emit<T>(value: T, render: () => string): void` reading `process.env.VELA_OUTPUT_JSON === "1"` and `VELA_OUTPUT_QUIET === "1"`.

- [ ] **Step 1: Write failing tests** in `cli/src/output.test.ts`

```ts
import { expect, test } from "bun:test"
import { emit } from "./output"

test("emit prints JSON when VELA_OUTPUT_JSON is set", () => {
  const saved = process.env.VELA_OUTPUT_JSON
  process.env.VELA_OUTPUT_JSON = "1"
  const lines: string[] = []
  const log = console.log; console.log = (value: string) => lines.push(value)
  try { emit({ a: 1 }, () => "human") } finally {
    console.log = log
    if (saved === undefined) delete process.env.VELA_OUTPUT_JSON; else process.env.VELA_OUTPUT_JSON = saved
  }
  expect(lines[0]).toBe('{\n  "a": 1\n}')
})

test("emit suppresses output when quiet is set, including over json", () => {
  const savedJson = process.env.VELA_OUTPUT_JSON, savedQuiet = process.env.VELA_OUTPUT_QUIET
  process.env.VELA_OUTPUT_JSON = "1"; process.env.VELA_OUTPUT_QUIET = "1"
  const lines: string[] = []
  const log = console.log; console.log = (value: string) => lines.push(value)
  try { emit({ a: 1 }, () => "human") } finally {
    console.log = log
    if (savedJson === undefined) delete process.env.VELA_OUTPUT_JSON; else process.env.VELA_OUTPUT_JSON = savedJson
    if (savedQuiet === undefined) delete process.env.VELA_OUTPUT_QUIET; else process.env.VELA_OUTPUT_QUIET = savedQuiet
  }
  expect(lines).toEqual([])
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd cli && bun test src/output.test.ts`
Expected: FAIL — cannot resolve `./output`.

- [ ] **Step 3: Create `cli/src/output.ts`**

```ts
export function emit<T>(value: T, render: () => string): void {
  if (process.env.VELA_OUTPUT_QUIET === "1") return
  if (process.env.VELA_OUTPUT_JSON === "1") { console.log(JSON.stringify(value, null, 2)); return }
  console.log(render())
}
```

In `cli/src/main.ts` `applyGlobalConfig`, add the two flags (both `--json`/`--quiet` and `--json=`/`--quiet=` forms; a bare `--json`/`--quiet` sets `"1"`). Add them to `HELP`.

- [ ] **Step 4: Refactor existing JSON-capable commands to use `emit`**

In `deploy.ts`, `containers.ts` and `tokens.ts`, delete their local `json` flag handling and replace each `if (json) console.log(JSON.stringify(x, null, 2)); else ...` with `emit(x, () => humanString)`. Do the same for `whoami` in `cli/src/commands/auth.ts` (local `json` option, lines 86-95): convert it to `emit(me, render)` with the existing human string as the render callback — once `applyGlobalConfig` strips a global `--json`, whoami's own `parseArgs` never sees it and would silently print human text. Keep the existing human strings byte-for-byte (including `formatTable(...)` calls). `--json` is now consumed globally, so remove `json: { type: "boolean" }` from those commands' `parseArgs` options.

- [ ] **Step 5: Run tests and typecheck**

Run: `cd cli && bun test && bun run typecheck`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add cli/src/output.ts cli/src/output.test.ts cli/src/main.ts cli/src/commands/deploy.ts cli/src/commands/containers.ts cli/src/commands/tokens.ts cli/src/commands/auth.ts
git commit -m "feat(cli): add uniform --json and --quiet output"
```

---

### Task 4: F11 — shell completions

**Files:**
- Create: `cli/src/commands/completion.ts`
- Modify: `cli/src/main.ts`, `cli/README.md`
- Test: `cli/src/commands/completion.test.ts`

**Interfaces:**
- Consumes: command names from `HELP`.
- Produces: `completionCommand(argv: string[]): Promise<number>`.

- [ ] **Step 1: Write failing tests**

```ts
import { expect, test } from "bun:test"
import { completionCommand } from "./completion"

test("each supported shell script contains every command", async () => {
  for (const shell of ["bash", "zsh", "fish", "powershell"]) {
    const lines: string[] = []
    const log = console.log; console.log = (value: string) => lines.push(value)
    try { expect(await completionCommand([shell])).toBe(0) } finally { console.log = log }
    const script = lines.join("\n")
    for (const command of ["run", "ps", "deploys", "stack", "projects", "metrics", "config"]) {
      expect(script).toContain(command)
    }
  }
})

test("unsupported shell is a usage error", async () => {
  expect(completionCommand(["tcsh"])).rejects.toThrow()
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd cli && bun test src/commands/completion.test.ts`
Expected: FAIL — cannot resolve `./completion`.

- [ ] **Step 3: Create `cli/src/commands/completion.ts`**

```ts
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
```

- [ ] **Step 4: Register `completion` in `cli/src/main.ts`** (import + `case "completion": return await completionCommand(rest)` + HELP line).

- [ ] **Step 5: Run tests and typecheck**

Run: `cd cli && bun test && bun run typecheck`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add cli/src/commands/completion.ts cli/src/commands/completion.test.ts cli/src/main.ts
git commit -m "feat(cli): add shell completion generation"
```

---

### Task 5: F07 — stacks, projects, teams and invitations

**Files:**
- Create: `cli/src/commands/organisation.ts`
- Modify: `cli/src/main.ts`
- Test: `cli/src/commands/organisation.test.ts`

**Interfaces:**
- Consumes: `request`, `requireToken`, `resolveConfig`, `VelaError` from `../client`; `emit` from `../output`.
- Produces: `stackCommand`, `projectsCommand`, `teamsCommand`, `inviteCommand`.

- [ ] **Step 1: Write failing tests with a stubbed `globalThis.fetch`** (pattern from `cli/src/ws.test.ts`):

```ts
import { expect, test, beforeEach, afterEach } from "bun:test"
import { stackCommand, projectsCommand, inviteCommand } from "./organisation"

const originalFetch = globalThis.fetch
const originalConfig = process.env.VELA_CONFIG
const originalToken = process.env.VELA_TOKEN
const calls: { method: string; url: string }[] = []
beforeEach(() => {
  calls.length = 0
  process.env.VELA_CONFIG = ""
  process.env.VELA_TOKEN = "pat_test"
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    calls.push({ method: init?.method ?? "GET", url: String(input) })
    return new Response(JSON.stringify([]), { status: 200, headers: { "content-type": "application/json" } })
  }) as typeof fetch
})
afterEach(() => {
  globalThis.fetch = originalFetch
  if (originalConfig === undefined) delete process.env.VELA_CONFIG; else process.env.VELA_CONFIG = originalConfig
  if (originalToken === undefined) delete process.env.VELA_TOKEN; else process.env.VELA_TOKEN = originalToken
})

test("stack list hits GET /api/stacks/", async () => {
  expect(await stackCommand(["list"])).toBe(0)
  expect(calls[0]).toEqual({ method: "GET", url: "http://127.0.0.1:8000/api/stacks/" })
})

test("projects create posts the name", async () => {
  expect(await projectsCommand(["create", "class-a"])).toBe(0)
  expect(calls[0].method).toBe("POST")
  expect(calls[0].url).toContain("/api/projects/")
})

test("invite list hits the project-scoped invitations endpoint", async () => {
  expect(await inviteCommand(["list", "--project", "prj_1"])).toBe(0)
  expect(calls[0].url).toContain("/api/projects/prj_1/invitations")
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd cli && bun test src/commands/organisation.test.ts`
Expected: FAIL — cannot resolve `./organisation`.

- [ ] **Step 3: Create `cli/src/commands/organisation.ts`**

```ts
import { parseArgs } from "node:util"
import { request, requireToken, resolveConfig, VelaError } from "../client"
import { emit } from "../output"
import { formatTable } from "../format"

interface ProjectPublic { id: string; name: string; role?: string }
interface StackPublic { id: string; project_id: string; name: string }
interface ProjectInvitationPublic { id: string; email: string; role: string }

function parse(argv: string[], options: Parameters<typeof parseArgs>[0]["options"]) {
  return parseArgs({ args: argv, options, allowPositionals: true })
}

export async function stackCommand(argv: string[]): Promise<number> {
  const action = argv[0] ?? "list"
  const { positionals, values } = parse(argv.slice(1), {
    project: { type: "string" }, "manifest": { type: "string" },
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
  const { positionals } = parse(argv.slice(1), {})
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
  const { positionals, values } = parse(argv.slice(1), { project: { type: "string" } })
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
```

- [ ] **Step 4: Register `stack`, `projects`, `teams`, `invite` in `main.ts`** (imports + four switch cases + HELP lines).

- [ ] **Step 5: Run tests and typecheck**

Run: `cd cli && bun test && bun run typecheck`
Expected: PASS. Note: admin/instructor gates are not pre-checked — a 403 surfaces as exit code 3 through `exitCodeFor`.

- [ ] **Step 6: Commit**

```bash
git add cli/src/commands/organisation.ts cli/src/commands/organisation.test.ts cli/src/main.ts
git commit -m "feat(cli): add stack, project, team and invite commands"
```

---

### Task 6: F07 — templates, scaling, metrics and audit

**Files:**
- Create: `cli/src/commands/ops.ts`
- Modify: `cli/src/main.ts`
- Test: `cli/src/commands/ops.test.ts`

**Interfaces:**
- Consumes: `request`, `requireToken`, `resolveConfig`, `VelaError`; `emit`; `formatTable`.
- Produces: `templatesCommand`, `scaleCommand`, `metricsCommand`, `auditCommand`; `printRows<T>(rows, headers, cells)` helper used by this file only.

- [ ] **Step 1: Write failing tests** in `cli/src/commands/ops.test.ts` with a stubbed `fetch`:

```ts
import { expect, test, beforeEach, afterEach } from "bun:test"
import { templatesCommand, scaleCommand, metricsCommand, auditCommand } from "./ops"

const originalFetch = globalThis.fetch
const originalConfig = process.env.VELA_CONFIG
const originalToken = process.env.VELA_TOKEN
const calls: { method: string; url: string }[] = []
beforeEach(() => {
  calls.length = 0
  process.env.VELA_CONFIG = ""
  process.env.VELA_TOKEN = "pat_test"
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    calls.push({ method: init?.method ?? "GET", url })
    const body = url.includes("audit") ? JSON.stringify({ entries: [], total: 0 }) : JSON.stringify([])
    return new Response(body, { status: 200, headers: { "content-type": "application/json" } })
  }) as typeof fetch
})
afterEach(() => {
  globalThis.fetch = originalFetch
  if (originalConfig === undefined) delete process.env.VELA_CONFIG; else process.env.VELA_CONFIG = originalConfig
  if (originalToken === undefined) delete process.env.VELA_TOKEN; else process.env.VELA_TOKEN = originalToken
})

test("templates list hits GET /api/dockerfiles/", async () => {
  expect(await templatesCommand(["list"])).toBe(0)
  expect(calls[0]).toEqual({ method: "GET", url: "http://127.0.0.1:8000/api/dockerfiles/" })
})
test("scale read uses GET /api/scaling/policies", async () => {
  expect(await scaleCommand(["list"])).toBe(0)
  expect(calls[0].url).toContain("/api/scaling/policies")
})
test("metrics usage hits GET /api/metrics/usage", async () => {
  expect(await metricsCommand(["usage"])).toBe(0)
  expect(calls[0].url).toContain("/api/metrics/usage")
})
test("audit defaults to the user-scoped log", async () => {
  expect(await auditCommand(["list"])).toBe(0)
  expect(calls[0].url).toContain("/api/audit/log")
})
test("audit --global uses the admin endpoint", async () => {
  expect(await auditCommand(["list", "--global"])).toBe(0)
  expect(calls[0].url).toContain("/api/admin/audit")
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd cli && bun test src/commands/ops.test.ts`
Expected: FAIL — cannot resolve `./ops`.

- [ ] **Step 3: Create `cli/src/commands/ops.ts`**

```ts
import { parseArgs } from "node:util"
import { request, requireToken, resolveConfig, VelaError } from "../client"
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
```

- [ ] **Step 4: Register `templates`, `scale`, `metrics`, `audit` in `main.ts`** (imports, switch cases, HELP lines).

- [ ] **Step 5: Run tests and typecheck**

Run: `cd cli && bun test && bun run typecheck`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add cli/src/commands/ops.ts cli/src/commands/ops.test.ts cli/src/main.ts
git commit -m "feat(cli): add templates, scaling, metrics and audit commands"
```

---

### Task 7: F07 — images, sources, settings and GitHub status

**Files:**
- Create: `cli/src/commands/platform.ts`
- Modify: `cli/src/main.ts`
- Test: `cli/src/commands/platform.test.ts`

**Interfaces:**
- Consumes: `request`, `requireToken`, `resolveConfig`, `VelaError`; `emit`; `formatTable`.
- Produces: `imagesCommand`, `sourcesCommand`, `settingsCommand`, `githubCommand`.

- [ ] **Step 1: Write failing tests** in `cli/src/commands/platform.test.ts`:

```ts
import { expect, test, beforeEach, afterEach } from "bun:test"
import { imagesCommand, sourcesCommand, settingsCommand, githubCommand } from "./platform"

const originalFetch = globalThis.fetch
const originalConfig = process.env.VELA_CONFIG
const originalToken = process.env.VELA_TOKEN
const calls: { method: string; url: string }[] = []
beforeEach(() => {
  calls.length = 0
  process.env.VELA_CONFIG = ""
  process.env.VELA_TOKEN = "pat_test"
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    calls.push({ method: init?.method ?? "GET", url })
    const body = url.includes("deploy-sources") ? JSON.stringify({ suggestions: [] }) : JSON.stringify([])
    return new Response(body, { status: 200, headers: { "content-type": "application/json" } })
  }) as typeof fetch
})
afterEach(() => {
  globalThis.fetch = originalFetch
  if (originalConfig === undefined) delete process.env.VELA_CONFIG; else process.env.VELA_CONFIG = originalConfig
  if (originalToken === undefined) delete process.env.VELA_TOKEN; else process.env.VELA_TOKEN = originalToken
})

test("images list hits GET /api/images/", async () => {
  expect(await imagesCommand(["list"])).toBe(0)
  expect(calls[0]).toEqual({ method: "GET", url: "http://127.0.0.1:8000/api/images/" })
})
test("images pull posts to the admin endpoint", async () => {
  expect(await imagesCommand(["pull", "nginx", "--tag", "1.27"])).toBe(0)
  expect(calls[0].method).toBe("POST")
  expect(calls[0].url).toContain("/api/images/pull?image=nginx&tag=1.27")
})
test("sources list hits /api/containers/deploy-sources", async () => {
  expect(await sourcesCommand(["list"])).toBe(0)
  expect(calls[0].url).toContain("/api/containers/deploy-sources")
})
test("settings show hits /api/settings/ai-prefill", async () => {
  expect(await settingsCommand(["show"])).toBe(0)
  expect(calls[0].url).toContain("/api/settings/ai-prefill")
})
test("github status hits /api/auth/github/status", async () => {
  expect(await githubCommand(["status"])).toBe(0)
  expect(calls[0].url).toContain("/api/auth/github/status")
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd cli && bun test src/commands/platform.test.ts`
Expected: FAIL — cannot resolve `./platform`.

- [ ] **Step 3: Create `cli/src/commands/platform.ts`**

```ts
import { parseArgs } from "node:util"
import { request, requireToken, resolveConfig, VelaError } from "../client"
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
  const response = await request<{ suggestions: Array<{ kind: string; name?: string; id?: string; image?: string; git_url?: string }> }>(config, "GET", "/containers/deploy-sources?q=")
  const label = (suggestion: { kind: string; name?: string; id?: string; image?: string; git_url?: string }): string =>
    `${suggestion.kind}: ${suggestion.name ?? suggestion.image ?? suggestion.git_url ?? suggestion.id ?? ""}`
  emit(response, () => response.suggestions.map(label).join("\n"))
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
```

- [ ] **Step 4: Register `images`, `sources`, `settings`, `github` in `main.ts`** (imports, switch cases, HELP lines).

- [ ] **Step 5: Run tests and typecheck**

Run: `cd cli && bun test && bun run typecheck`
Expected: PASS. Admin-only endpoints are allowed to fail with a 403 → exit code 3; no local role pre-check is added.

- [ ] **Step 6: Commit**

```bash
git add cli/src/commands/platform.ts cli/src/commands/platform.test.ts cli/src/main.ts
git commit -m "feat(cli): add images, sources, settings and github commands"
```

---

### Task 8: F07 — stopped-container logs fallback, `--project` docs and CLI README

**Files:**
- Modify: `cli/src/commands/logs.ts`, `cli/README.md`
- Test: `cli/src/commands/logs.test.ts`

**Interfaces:**
- Consumes: `streamLogs` from `../ws`, `request`, `requireToken`, `resolveConfig`, `resolveContainerFromApi` from `../resolve`, `emit` from `../output`.
- Produces: `logs` command falls back to `GET /containers/{id}/logs?tail=<n>` when the WebSocket stream fails.

- [ ] **Step 1: Write a failing test for the fallback**

```ts
import { expect, test, beforeEach, afterEach } from "bun:test"
import { logs } from "./logs"

const originalFetch = globalThis.fetch
const originalConfig = process.env.VELA_CONFIG
const originalToken = process.env.VELA_TOKEN
const calls: string[] = []
beforeEach(() => {
  calls.length = 0
  process.env.VELA_CONFIG = ""
  process.env.VELA_TOKEN = "pat_test"
})
afterEach(() => {
  globalThis.fetch = originalFetch
  if (originalConfig === undefined) delete process.env.VELA_CONFIG; else process.env.VELA_CONFIG = originalConfig
  if (originalToken === undefined) delete process.env.VELA_TOKEN; else process.env.VELA_TOKEN = originalToken
})

test("a failed stream falls back to the HTTP log snapshot", async () => {
  const config = { server: "http://127.0.0.1:8000", token: "pat" }
  globalThis.fetch = (async (input: RequestInfo | URL) => {
    const url = String(input)
    calls.push(url)
    if (url.includes("/by-name/")) {
      return new Response(JSON.stringify({ id: "c1", name: "web", status: "exited" }), { status: 200, headers: { "content-type": "application/json" } })
    }
    if (url.includes("/logs")) {
      return new Response(JSON.stringify({ logs: "line one\nline two" }), { status: 200, headers: { "content-type": "application/json" } })
    }
    return new Response("[]", { status: 200, headers: { "content-type": "application/json" } })
  }) as typeof fetch
  const lines: string[] = []
  const log = console.log; console.log = (value: string) => lines.push(value)
  try { expect(await logs(["web"])).toBe(0) } finally { console.log = log }
  expect(calls.some((url) => url.includes("/api/containers/c1/logs"))).toBe(true)
  expect(lines.join("\n")).toContain("line one")
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd cli && bun test src/commands/logs.test.ts`
Expected: FAIL — fallback does not exist.

- [ ] **Step 3: Add the fallback in `cli/src/commands/logs.ts`**

Wrap the existing `streamLogs(...)` call in `try { ... } catch { ... }`. In the catch branch, fetch the snapshot and emit it:

```ts
} catch {
  const snapshot = await request<{ logs: string }>(
    config, "GET", `/containers/${encodeURIComponent(container.id)}/logs?tail=${tail ?? 100}`,
  )
  emit(snapshot, () => snapshot.logs)
}
```

Keep the existing `-f/--follow` and `-n/--tail` parsing. If `--follow` was requested, print a one-line `console.error("Stream unavailable; showing a snapshot instead")` before the fallback output.

- [ ] **Step 4: Document the new commands in `cli/README.md`**

Replace the Commands table with one that lists the commands registered in Tasks 2–8 (`config`, `completion`, `stack`, `projects`, `teams`, `invite`, `templates`, `scale`, `metrics`, `audit`, `images`, `sources`, `settings`, `github`) alongside the existing ones. Add short sections: "Profiles" (`--profile`, `VELA_PROFILE`, `vela config use|list|get|set`, legacy file migration), "Scriptable output" (global `--json`/`--quiet`), and "Completion" (`vela completion <shell>`). Keep `--no-wait` described as already supported.

- [ ] **Step 5: Run full CLI verification**

Run: `cd cli && bun test && bun run typecheck && bun run build`
Expected: PASS (build emits `dist/vela`).

- [ ] **Step 6: Commit**

```bash
git add cli/src/commands/logs.ts cli/src/commands/logs.test.ts cli/README.md
git commit -m "feat(cli): add logs snapshot fallback and document new commands"
```

---

## Self-review (done at plan authoring)

- **Spec coverage:** F11 → Tasks 1–4; F07 → Tasks 5–8; `--no-wait` explicitly out of scope; admin/instructor gates handled by surfacing backend 403; `--project` implemented as client-side filter or project-scoped path where the endpoint supports it.
- **Placeholder scan:** no TBD/TODO; every code step contains concrete code or exact command.
- **Type consistency:** `resolveConfig(flags, env, stored)` from Task 1 is the signature used by all later tasks; `emit(value, render)` from Task 3 is reused unchanged; new command exports are registered by name in `main.ts` in the same task that creates them.
