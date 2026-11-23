# vela CLI

Terminal client for Vela. Runs on Bun; ships as a compiled binary.

Linux/macOS: use `dist/vela` (no `.exe`) and `export VAR=value` instead of `$env:VAR = "value"`.

## Install

```powershell
cd cli
bun install
bun run build        # dist/vela.exe on Windows
```

## Log in

```powershell
vela login --server http://127.0.0.1:8000
```

`vela login` exchanges your email and password for a long-lived personal access
token and stores it in `~/.vela/config.json`. The password is never saved.

For CI, skip login and use environment variables:

```powershell
$env:VELA_API_URL = "http://127.0.0.1:8000"
$env:VELA_TOKEN = "vela_pat_..."
```

## Commands

| Command | Purpose |
|---|---|
| `vela ps [--json]` | List containers |
| `vela describe <name> [--json]` | One container, with stats |
| `vela run <git-url\|image>` | Deploy; flags `--name --port --env K=V --public --branch --template --project --no-wait` |
| `vela logs <name> [-f] [-n 200]` | Stream logs; falls back to an HTTP snapshot if the stream is unavailable |
| `vela exec <name> [-- cmd]` | Shell into a container |
| `vela start\|stop\|restart\|rm <name>` | Lifecycle (`rm -y` to skip the prompt) |
| `vela deploys [--json]` | Deployment history |
| `vela tokens list\|create\|revoke` | Manage access tokens |
| `vela stack <list\|deploy\|rm>` | Manage stacks (`list --project <id>` filters by project) |
| `vela projects <list\|create>` | Manage projects |
| `vela teams <list\|create>` | Manage teams |
| `vela invite <list\|create\|cancel>` | Manage project invitations (requires `--project <id>`) |
| `vela templates <list\|create\|rm>` | Manage Dockerfile templates |
| `vela scale <list\|set>` | Manage scaling policies |
| `vela metrics <usage\|summary>` | Usage/metrics (`--container`, `--hours`) |
| `vela audit <list>` | Audit log (`--global` uses the admin endpoint, `--limit`) |
| `vela images <list\|pull>` | List images or pull one (`--tag`) |
| `vela sources <list>` | List deploy sources |
| `vela settings <show\|monitoring\|github-status>` | Platform settings |
| `vela github <status>` | GitHub connection status |
| `vela config <list\|use\|get\|set\|clear>` | Manage config profiles |
| `vela completion <bash\|zsh\|fish\|powershell>` | Print a shell completion script |
| `vela` | Terminal UI |

`vela run` waits for the deploy by default; `--no-wait` returns the job id immediately.

Exit codes: `0` ok, `1` failure, `2` usage, `3` auth, `4` not found.

## Profiles

Named profiles in `~/.vela/config.json` hold a server and token each. Select one
with `--profile <name>` on any command or `VELA_PROFILE`; `vela config list` shows
them and `vela config use <name>` sets the default. Inspect with `vela config get
[server\|token\|tokenId]` and update with `vela config set <server\|token> <value>
[--profile <name>]`; `vela config clear` removes the file. A legacy flat
`{ "server", "token" }` file is migrated into the `default` profile on first read.

## Scriptable output

Global flags (before `--` on any command): `--json` prints the result as JSON and
`--quiet` suppresses command output. One-time credentials are never suppressed.
Env equivalents: `VELA_OUTPUT_JSON=1` and `VELA_OUTPUT_QUIET=1`.

## Completion

`vela completion <bash\|zsh\|fish\|powershell>` prints a script to source from
your shell profile or save in your shell's completions directory.

## Manual smoke

With the API running locally:

```powershell
vela login
vela whoami
vela ps
vela run nginx:alpine --name smoke --public
vela logs smoke -n 20
vela exec smoke -- sh -c "echo hello"
vela stop smoke
vela rm smoke -y
vela tui
```
