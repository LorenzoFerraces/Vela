---
name: trello-user-stories-delivery-report
description: >-
  Produces a Markdown delivery report from Trello card URLs used as scope references,
  organized by synthesized user stories (not one section per card), grounded in the
  repository at a chosen Git tag, commit, or GitHub release. Use when the user pastes
  Trello links, asks for entrega / iteration documentation, user stories mapped to code,
  or a POC/release delivery write-up similar to docs/entrega-poc-historias-de-usuario.md.
disable-model-invocation: true
---

# Trello cards → delivery report by user story (Markdown)

## When to use

Apply when the user provides **one or more Trello card URLs** (and optionally a **GitHub release** or **tag/commit**) and wants a **structured Markdown document** for an academic or stakeholder delivery, aligned with what the codebase actually implements.

**Cards are scope pointers, not the document outline.** Use them to learn what was planned or claimed in Trello; then write the report at the level of **user stories as a whole**—coherent outcomes an actor cares about—not one subsection per card.

## Inputs to confirm (ask only if missing)

1. **Trello cards**: full URLs `https://trello.com/c/<CARD_ID>/...` (dedupe by `CARD_ID`). Read titles/slugs (and descriptions if available) to infer scope; do not mirror card granularity in the final doc.
2. **Scope**: default **current workspace** at **HEAD**; if they cite a **release or tag**, resolve the **commit SHA** (`git rev-parse <tag>^{commit}`) and prefer `git show <SHA>:path` / `git ls-tree` when describing behavior so the report matches that snapshot.
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
3. **Ground truth** for Funcionalidad and Criterios de aceptación is always **code, tests, CI, and README** in scope—not card wording alone.

When several cards map to one story, cite **all relevant Trello links** under that story (comma-separated or bullet list under **Trello:**).

## Document structure (use this order)

1. **Title** — e.g. `# Documentación de entrega — <iteración> (<proyecto>)`
2. **Release reference** (if applicable) — link to GitHub release and short line with **tag + commit** and repo link.
3. **`## User stories`** — one subsection per **synthesized user story** (not per card).
4. **`## Resumen ejecutivo`** — bullets for what shipped **in scope as a whole**; call out anything **after** the pinned commit that differs from **current HEAD** if they mixed scope.
5. **`### Decisiones tomadas`** (under resumen or as `##`) — priorities, technical tradeoffs, spikes, tooling, env constraints across the iteration.
6. **`## Consejos`** (optional, short) — Markdown conventions, verifiable acceptance criteria, linking Trello/GitHub.

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

- **Title**: outcome-focused name for the whole story (not a card slug copy unless it already matches the story).
- **Funcionalidad** / **Criterios de aceptación**: describe the **complete** story—include frontend, backend, routing, CI, etc. in one row when they jointly deliver the outcome.
- **Actor(es)**: who benefits or operates the feature (end user, developer, operator, CI).
- **Valor**: one or two sentences, outcome-focused.

## Quality bar

- **Verifiable acceptance criteria** (commands, endpoints, UI flows, CI job names) over vague wording.
- If the repo **does not implement** part of the synthesized scope, state that honestly and separate “planned” from “shipped in scope.”
- **Deduplicate** duplicate Trello links; **do not duplicate** the same narrative across multiple story sections because it appeared on multiple cards.
- Match **existing project tone** in `docs/` if prior entregas exist.

## Optional intro line (Spanish deliveries)

If the course or stakeholder pack expects it, add under the title:

> A continuación presentamos la documentación que vamos a exigirles en cada entrega.

(Omit if the user says their template does not use it.)

## Reference example in this repo

See `docs/entrega-poc-historias-de-usuario.md` for tone and table shape. That file may still list one subsection per card from an earlier pass; **new reports** should follow this skill’s **story-level** grouping even when many Trello links were provided.
