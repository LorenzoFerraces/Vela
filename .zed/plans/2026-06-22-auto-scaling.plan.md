---
name: Auto Scaling Implementation
overview: Implement persistent autoscaling policies, integrate them into container deployment, and build a periodic scaling loop.
todos:
  - id: create-scaling-table
    content: Add migration for `scaling_policies` table via alembic
    status: pending
  - id: pydantic-schema
    content: Create Pydantic schema for ScalingPolicy
    status: pending
  - id: api-endpoints
    content: Expose POST /api/containers/run & PATCH by workload_id
    status: pending
  - id: validate-inputs
    content: Validate min_replicas, max_replicas, target_cpu_percent, cooldown_seconds
    status: pending
  - id: update-run-form
    content: Add autoscaling fields to run endpoint and form payload
    status: pending
  - id: scaling-loop-task
    content: Create asyncio task in FastAPI lifespan for periodic scaling logic
    status: pending
  - id: scale-up-proc
    content: Deploy replica, same image/config, labels vela.workload_id & owner_id
    status: pending
  - id: scale-down-proc
    content: Remove excess replicas respecting cooldown_seconds
    status: pending
  - id: traefik-service
    content: Create Traefik multi-backend service per workload
    status: pending
  - id: cleanup-0-replicas
    content: Delete Traefik route when replicas reach zero
    status: pending
  - id: tests-orchestrator-mock
    content: Mock orchestrator for integration tests of scaling logic
    status: pending
  - id: ui-form-autoscaling
    content: Add Autoscaling toggle section to run form, disable/enable fields
    status: pending
  - id: docs-helper-text
    content: Provide helper text for autoscaling inputs in UI
    status: pending
  - id: error-422
    content: Ensure 422 errors are returned when validation fails
    status: pending
isProject: false
---
# Auto Scaling Implementation
> **Created:** 2026‑06‑22
>
> **Request:** Implement autoscaling policy persistence, form integration, and scaling logic per cards #64‑66.
> > **Status:** 🟡 Pending
>
> 
> ## 1. What Exists Today
> The repo currently lacks persistent autoscaling policies; the `/api/containers/run` route accepts a generic payload but does not handle autoscaling fields, and no scaling loop exists.
>
> ## 2. What We Will Be Doing
> Create migration + schema, API endpoints with validation, extend run form to send policy data, implement a periodic asyncio task that checks CPU against target and scales up/down via orchestrator APIs while updating Traefik multi‑backend services.
> 
> ## 3. Flow / Architecture Diagram
>
> ```mermaid
graph TD
>A[Container Deploy] -->|"policy_id = vela.workload_id"| B[ScalingPolicy DB]
>B --> C{"autoscaling?"}
>C -- No --> Z[Do nothing]
>C -- Yes --> D[Scale Loop task per workload in lifespan]
>D --> E{CPU > target ? scale_up : scale_down}
>E --> F{"Deploy/Remove replica, update Traefik service"}
>```