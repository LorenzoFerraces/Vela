# vela CLI

Terminal client for Vela. Runs on Bun; ships as a compiled binary.

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
| `vela run <git-url\|image>` | Deploy; flags `--name --port --env K=V --public --branch --template` |
| `vela logs <name> [-f] [-n 200]` | Logs |
| `vela exec <name> [-- cmd]` | Shell into a container |
| `vela start\|stop\|restart\|rm <name>` | Lifecycle (`rm -y` to skip the prompt) |
| `vela deploys [--json]` | Deployment history |
| `vela tokens list\|create\|revoke` | Manage access tokens |
| `vela` | Terminal UI |

Exit codes: `0` ok, `1` failure, `2` usage, `3` auth, `4` not found.

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
