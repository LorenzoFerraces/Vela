# Multi-App Stack Deployments

**Date:** 2026-07-31  
**Status:** Approved  

## Problem

Vela currently deploys one container at a time. Real applications often consist of multiple services (backend, frontend, database) that need to be deployed together on a shared network. Users want to define and deploy these groups as a unit.

## Solution

Introduce **Stacks** — a native model for multi-service deployments. A stack groups services that share a Docker network. Services are deployed together but managed independently after creation. Stacks support composition (nesting) and can be created via a visual builder or by importing a docker-compose.yml file.

## Architecture

```
Organization
  └── Project
        ├── Containers (existing, standalone)
        └── Stacks (new)
              ├── Stack A
              │     ├── Service: frontend → container
              │     ├── Service: backend → container
              │     └── Service: db → container
              └── Stack B (references Stack A)
                    └── inherits Stack A services + own services
```

- A **Stack** belongs to a single Project. All services inherit project access control.
- A **StackService** maps to one container. Services communicate via a shared Docker network.
- A **StackComposition** links a parent stack to a child stack. The child's services join the parent's network on deploy. Child stacks are reusable across multiple parents.

## Data Model

### `stacks`
| Column | Type | Constraints |
|--------|------|-------------|
| id | UUID | PK, default uuid4 |
| project_id | UUID | FK → projects.id, NOT NULL, indexed, cascade delete |
| name | String(128) | NOT NULL |
| network_name | String(128) | NOT NULL, unique |
| created_at | DateTime(tz) | NOT NULL, default utcnow |
| updated_at | DateTime(tz) | NOT NULL, default utcnow, onupdate utcnow |

Unique constraint: `(project_id, name)`

### `stack_services`
| Column | Type | Constraints |
|--------|------|-------------|
| id | UUID | PK, default uuid4 |
| stack_id | UUID | FK → stacks.id, NOT NULL, indexed, cascade delete |
| service_name | String(128) | NOT NULL |
| source_kind | String(32) | NOT NULL — `image`, `git`, `dockerfile_template` |
| source_ref | String(2048) | NOT NULL — image ref, git URL, or template ID |
| container_port | Integer | NOT NULL, default 80 |
| env_vars | JSON | NOT NULL, default {} |
| command | JSON | nullable |
| public_route | Boolean | NOT NULL, default false |
| depends_on | JSON | nullable — array of service_names (informational) |
| created_at | DateTime(tz) | NOT NULL, default utcnow |

Unique constraint: `(stack_id, service_name)`

### `stack_compositions`
| Column | Type | Constraints |
|--------|------|-------------|
| parent_stack_id | UUID | FK → stacks.id, NOT NULL, cascade delete |
| child_stack_id | UUID | FK → stacks.id, NOT NULL, cascade delete |

Unique constraint: `(parent_stack_id, child_stack_id)`

Application-level: reject self-references and cycles.

### `deployment_records` (existing, modified)
- Add `stack_id` column: UUID, FK → stacks.id, nullable, SET NULL on delete, indexed

## API

New router: `/api/stacks`

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | List stacks for current user's projects |
| `POST` | `/` | Create stack from services array (visual builder path) |
| `POST` | `/import-compose` | Import from docker-compose YAML |
| `GET` | `/{stack_id}` | Stack detail with services and compositions |
| `DELETE` | `/{stack_id}` | Delete stack (stops containers, removes network) |
| `POST` | `/{stack_id}/deploy` | Deploy all services in stack |

`POST /` body: `{ project_id, name, services: [StackServiceCreate] }`
`POST /import-compose` body: `{ project_id, name, yaml_content }`

Compose import returns `StackPublic` + `compose_warnings` array describing dropped features.

## Compose Parser

`app/core/stacks/compose_parser.py`

**Supported:**
- `services.*.image` → `source_kind: image`, `source_ref: <image>`
- `services.*.build.context` → `source_kind: git` (if context is a git URL) or `dockerfile_template`
- `services.*.environment` → `env_vars`
- `services.*.ports` → `container_port` (container side)
- `services.*.command` → `command`
- `services.*.depends_on` → `depends_on`
- Top-level `networks` — ignored (Vela creates its own network)

**Unsupported (warning emitted, service still created):**
- `volumes`, `secrets`, `configs`, `deploy.resources`, `healthcheck`, `extends`, `include`, custom `networks` per service

## Deployment Flow

`POST /api/stacks/{stack_id}/deploy`:

1. Resolve composition DAG — topological sort, reject cycles
2. Flatten all services from parent + child stacks
3. Create Docker network: `vela-stack-{stack_id.hex[:12]}`
4. For each service (in dependency order):
   - Build `DeployConfig` with `network_mode` = stack network
   - Container name: `{stack_name}_{service_name}` (append hex suffix on collision)
   - Labels: `vela.stack_id`, `vela.service_name`
   - Deploy via existing orchestrator flow
   - Wire public route if requested
5. Persist `DeploymentRecord` for each service with `stack_id`
6. On any failure: stop all started containers, remove network, return error with failing service name

## Frontend

### Stack list (`/stacks`)
- Cards showing stack name, project, service count, deploy status
- "Create Stack" button → opens visual builder
- "Import Compose" button → opens YAML paste dialog

### Visual builder (`StackVisualizer.tsx`)
- `@xyflow/react` canvas with custom service nodes
- Node types: `ServiceNode` (standard), `StackReferenceNode` (collapsed child stack, expandable), `AddNode` (+ button)
- Pan, zoom, minimap controls
- Dependency edges between nodes
- Side panel (`StackServiceForm.tsx`) for editing selected node
- Mode toggle: Visual ↔ List view

### Service form
- Name, source kind selector (image/git/template), source input, port, env vars (key-value pairs), public route toggle, depends_on multi-select
- For stack references: dropdown to select existing stack

### New dependency
- `@xyflow/react` — node-based graph editor

## Error Handling

- **Cycle in composition** → reject with list of stacks involved
- **Unsupported compose feature** → warning, service created without feature
- **Network creation failure** → abort, no containers started
- **Partial deploy** → full rollback, return failing service and error
- **Duplicate service name** → validation error
- **Container name collision** → auto-suffix with random hex

## Testing

- **Unit:** compose parser (each feature → expected fields), cycle detection, topological sort
- **Integration:** create stack → deploy → verify containers on shared network → delete → verify cleanup (using `FakeContainerOrchestrator`)
- **E2E:** visual builder → deploy → verify containers page shows stack services

## Scope

Approximately 800-1000 lines of new code. No breaking changes to existing deployment flow. Existing containers and projects unaffected.
