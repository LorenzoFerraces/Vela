---
name: witness-user-story-architecture-report
description: >-
  Writes an academic-style architecture document for a chosen witness user story:
  layered deployment diagram (Mermaid), sequence diagram, export paths to Excalidraw
  / mermaid.live / diagrams.net, and one paragraph per named component (files, routes,
  classes). Use when the user asks for diagrama de arquitectura, entrega architecture,
  witness user story technical map, or documentation like docs/entrega-1-diagrama-arquitectura.md.
disable-model-invocation: true
---

# Witness user story → architecture report (diagrams + componentes)

## When to use

Apply when the user names a **single user story testigo** (end-to-end slice of the product) and wants the **same class of deliverable** as `docs/entrega-1-diagrama-arquitectura.md`: **general architecture** grounded in **this repo**, with **exportable diagrams** and **non-generic** component names.

## Inputs (ask only if missing)

1. **User story testigo** — short narrative: actor, goal, preconditions (e.g. “usuario ya logueado y GitHub conectado”), trigger, outcome. If vague, propose one concrete witness and confirm.
2. **Scope** — default **current workspace / HEAD**; if they give a **tag or commit**, use `git show <rev>:path` when citing behavior.
3. **Language** — default **Spanish** for headings and prose unless they request English.
4. **Outputs** — default:
   - `docs/<slug>-diagrama-arquitectura.md` (slug from story or iteration name they give),
   - `docs/diagrams/<slug>-arquitectura.excalidraw` (optional but **default on** unless they say skip Excalidraw).
5. **External examples** — optional links (course samples); include only if the user provides them.

## Workflow

1. **Trace the story in code** — follow the path from UI or entrypoint to persistence and third-party systems. Grep/read routes, hooks, API clients, core services, DB models, config/env.
2. **Classify** — tag each touched piece as: **propio** vs **tercero**; layer: **vista**, **controller**, **dominio/core**, **persistencia**, **seguridad**, **infra externa** (Docker, SaaS, DB, proxy, etc.).
3. **Name concretely** — use **paths and symbols** (`frontend/src/...`, `backend/app/api/routes/foo.py`, `function_name`, `ClassName`). Do **not** write only “frontend” or “API”.
4. **Author diagrams**:
   - **Mermaid `flowchart`** — physical or logical nodes (client machine vs server), subgraphs by layer, third parties in separate subgraphs; arrows labeled with protocol or route when useful (`POST /api/...`, WebSocket, etc.).
   - **Mermaid `sequenceDiagram`** — same witness, main participants (keep names short if `<br/>` is fragile); happy path + one failure note only if essential.
5. **Excalidraw** — write a valid JSON document (see format below) with labeled boxes mirroring the flowchart (no fragile arrow bindings required; simple `arrow` elements with `points` are enough). Save as `.excalidraw`.
6. **Export section** — in the Markdown, include **copy-paste → [mermaid.live](https://mermaid.live) → PNG/SVG**, **Excalidraw Open → Export image**, and **diagrams.net** as optional.

## Markdown template (fill all sections)

Use this structure in order:

```markdown
# Diagrama de arquitectura — <título corto>

## 1. User story testigo
< párrafo actor + precondiciones + acción + resultado >

## 2. Leyenda: capas, propios vs terceros
| Convención | Significado |
|------------|-------------|
| **Propios** | … |
| **Terceros** | … |
| (filas por capas que apliquen) |

## 3. Diagrama general (Mermaid)
\`\`\`mermaid
flowchart TB
  ...
\`\`\`

## 4. Diagrama de secuencia (Mermaid)
\`\`\`mermaid
sequenceDiagram
  ...
\`\`\`

## 5. Exportar gráficos
### Opción A — Mermaid (mermaid.live → PNG/SVG)
### Opción B — Excalidraw (abrir .excalidraw → Export image)
### Opción C — diagrams.net (importar SVG o redibujar)

## 6. Responsabilidades por componente
### Vista / cliente (propio)
**`path/file.tsx`**  
< un párrafo >

### Controller …
**`path/routes.py` — `handler_name`**  
< un párrafo >

(continuar por cada pieza relevante; agrupar por capa)

## 7. Cierre (opcional)
Referencia de release/commit si aplica.
```

## Excalidraw file rules

- Top-level JSON: `"type": "excalidraw"`, `"version": 2`, `"source": "https://excalidraw.com"`, `"elements": [...]`, `"appState": { ... }`, `"files": {}`.
- Use `"updated": <ms timestamp>` on elements; set `"originalText"` equal to `"text"` on every `text` element.
- Prefer **rectangles + separate text** or text-only boxes; avoid `startBinding`/`endBinding` on arrows unless fully consistent (use `null` bindings and simple `points` on `arrow` types).

## Quality bar

- Diagrams must **match the witness** (no unrelated modules unless labeled “contexto”).
- If the story is **not implemented**, say so and diagram **planned** architecture clearly as hypothetical (dotted style in Mermaid or a warning callout).
- Keep **SKILL.md** concise; the generated report can be long.

## In-repo reference example

See **`docs/entrega-1-diagrama-arquitectura.md`** and **`docs/diagrams/vela-entrega1-arquitectura-deploy-git-privado.excalidraw`** for a completed instance (GitHub privado + deploy).
