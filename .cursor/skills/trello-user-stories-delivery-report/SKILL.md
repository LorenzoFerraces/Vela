---
name: trello-user-stories-delivery-report
description: >-
  Produces a Markdown delivery report from Trello card URLs used as scope references,
  organized by synthesized user stories (not one section per card), grounded in what
  the repository actually ships at a chosen Git tag, commit, or GitHub release. Written
  for stakeholders and end users: describes how people use each capability, not how it
  is implemented. Use when the user pastes Trello links, asks for entrega / iteration
  documentation, user stories mapped to shipped behavior, or a delivery write-up similar
  to docs/entrega-poc-historias-de-usuario.md.
disable-model-invocation: true
---

# Trello cards → delivery report by user story (Markdown)

## When to use

Apply when the user provides **one or more Trello card URLs** (and optionally a **GitHub release** or **tag/commit**) and wants a **structured Markdown document** for an academic or stakeholder delivery, aligned with what the product actually lets people do.

**Cards are scope pointers, not the document outline.** Use them to learn what was planned or claimed in Trello; then write the report at the level of **user stories as a whole**—coherent outcomes an actor cares about—not one subsection per card.

## Audience and voice (mandatory)

Write for **people who use the product**, not for developers maintaining the repo.

- Describe **what the user can do**, **where in the app they do it**, and **what they get** (feedback, limits, permissions).
- Use **screen names, menu labels, and everyday actions** (e.g. “en Settings activa alertas por email”, “invita a un compañero desde Teams”).
- **Do not** include implementation detail in the delivered document: no endpoints, migrations, table names, env vars, internal modules, Docker labels, CI job names, test file names, or stack-specific jargon unless the user explicitly asks for a technical appendix.

**Code, tests, CI, and README** are your **private ground truth** while drafting—use them to verify what shipped and to avoid inventing features—but **translate** findings into user-facing language in the final doc.

## Inputs to confirm (ask only if missing)

1. **Trello cards**: full URLs `https://trello.com/c/<CARD_ID>/...` (dedupe by `CARD_ID`). Read titles/slugs (and descriptions if available) to infer scope; do not mirror card granularity in the final doc.
2. **Scope**: default **current workspace** at **HEAD**; if they cite a **release or tag**, resolve the **commit SHA** (`git rev-parse <tag>^{commit}`) and inspect that snapshot when verifying behavior.
3. **Output path**: default `docs/entrega-<slug>-historias-de-usuario.md` or a path they specify.
4. **Language**: default **Spanish** for section prose and table cells; use another language only if they ask.
5. **Mockups row** in tables: **omit** unless the user explicitly wants mockups attached per story.

## From cards to user stories

Before writing:

1. **Inventory** what the linked cards refer to (titles, checklist items, labels, epic names if visible).
2. **Synthesize** into a small set of **user stories**—each with one actor, one outcome, one verifiable slice of value. Rules of thumb:
   - **Merge** cards that are split implementation of the same story (e.g. separate frontend/backend cards for one flow; setup subtasks that only make sense together).
   - **Do not** create a story section whose only purpose is to restate a single mechanical card (“add file X”) unless that card truly is an independent user-visible outcome.
   - **Order** stories for readability (dependency, user journey, or importance)—not necessarily the order cards were pasted.
3. **Verify** against code/tests in scope, then **write only the user-visible behavior** in Funcionalidad and Criterios de aceptación.

When several cards map to one story, cite **all relevant Trello links** under that story (comma-separated or bullet list under **Trello:**).

## Document structure (use this order)

1. **Title** — e.g. `# Documentación de entrega — <iteración> (<proyecto>)`
2. **Release reference** (if applicable) — link to GitHub release and short line with **tag + commit** and repo link (this is the only place where commit/tag detail is expected).
3. **`## User stories`** — one subsection per **synthesized user story** (not per card).
4. **`## Resumen ejecutivo`** — bullets of **outcomes for users** in scope as a whole; call out anything **after** the pinned commit that differs from **current HEAD** if they mixed scope.
5. **`### Decisiones tomadas`** (under resumen or as `##`) — **product and UX choices** visible to users (permissions, opt-in flows, what lives in which screen, deliberate limits). Avoid internal refactors, test fixes, or tooling unless they change what the client can do.
6. **`## Consejos`** (optional, short) — how to keep future entregas user-focused, link Trello/GitHub, write verifiable acceptance criteria in plain language.

## Per user story subsection template

For each **synthesized** story:

```markdown
### <n>. <Short title>

**Trello:** [<link text>](<url>) · … *(only cards that belong to this story)*

| Campo | Descripción |
|--------|-------------|
| **Actor(es)** | … |
| **Funcionalidad** | … |
| **Valor** | … |
| **Criterios de aceptación** | … |
```

### Field guidance (user-facing only)

- **Title**: outcome-focused name for the whole story (not a card slug copy unless it already matches the story).
- **Actor(es)**: who uses or benefits from the feature (e.g. operador, miembro del equipo, invitado). Avoid “el sistema”, “CI”, or “API” as primary actors unless the story is explicitly about automated behavior **as experienced by the user** (e.g. “recibe un email sin tener que revisar el panel”).
- **Funcionalidad**: narrate the **journey and screens**—what the person sees, chooses, and what happens next. Mention roles and permissions in human terms (puede ver / puede iniciar o detener / no puede eliminar). One cohesive paragraph or short bullets; **no** file paths, routes like `/api/…`, or database schema.
- **Valor**: one or two sentences on **why it matters** to the actor (time saved, control, collaboration, peace of mind).
- **Criterios de aceptación**: **observable from the client’s perspective**—scenarios a reviewer can walk through in the UI or inboxes, phrased as Given/When/Then or checklist items. Examples: “Si un contenedor deja de estar sano y tengo alertas activadas, recibo un correo”; “Un invitado no aparece en el equipo hasta que acepta”; “Un viewer ve workloads pero no puede detenerlos”. Do **not** cite pytest, Alembic, or HTTP status codes unless the product explicitly surfaces them to the user.

## Quality bar

- **Verifiable from usage**, not from the codebase: another person should confirm each criterion by using the app (or reading an email / invitation) without opening the repo.
- If the repo **does not implement** part of the synthesized scope, state that honestly and separate “planificado en Trello” from “disponible para el usuario en este ámbito”.
- **Deduplicate** duplicate Trello links; **do not duplicate** the same narrative across multiple story sections because it appeared on multiple cards.
- Match **existing project tone** in `docs/` for structure and table shape, but **prefer user-facing wording** over technical entregas written before this skill was updated.

## What to omit vs. keep

| Omit in user stories | OK in release header / footnotes |
|----------------------|----------------------------------|
| `POST /api/…`, WebSocket paths | Tag, commit SHA, repo URL |
| Migration numbers, table/column names | “Ámbito de código: commit …” |
| Env vars (`BREVO_*`, `VELA_*`) | Brief note if a feature requires admin setup **and** user asked to document deployment |
| Test names, CI workflows | — |
| Internal labels (`vela.owner_id`) | — |
| Module/function names | — |

## Optional intro line (Spanish deliveries)

If the course or stakeholder pack expects it, add under the title:

> A continuación presentamos la documentación que vamos a exigirles en cada entrega.

(Omit if the user says their template does not use it.)

## Reference example in this repo

See `docs/entrega-poc-historias-de-usuario.md` for table shape. Older files such as `docs/entrega-1-historias-de-usuario.md` may still contain technical detail from a previous style; **new reports** follow this skill’s **story-level grouping** and **user-facing voice**.
