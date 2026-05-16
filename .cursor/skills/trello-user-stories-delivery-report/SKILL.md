---
name: trello-user-stories-delivery-report
description: >-
  Produces a Markdown delivery report from a list of Trello user-story card URLs,
  grounded in the repository at a chosen Git tag, commit, or GitHub release.
  Use when the user pastes Trello links, asks for entrega / iteration documentation,
  user stories mapped to code, or a POC/release delivery write-up similar to
  docs/entrega-poc-historias-de-usuario.md.
disable-model-invocation: true
---

# Trello user stories → delivery report (Markdown)

## When to use

Apply when the user provides **one or more Trello card URLs** (and optionally a **GitHub release** or **tag/commit**) and wants a **structured Markdown document** for an academic or stakeholder delivery, aligned with what the codebase actually implements.

## Inputs to confirm (ask only if missing)

1. **Trello cards**: full URLs `https://trello.com/c/<CARD_ID>/...` (dedupe by `CARD_ID`).
2. **Scope**: default **current workspace** at **HEAD**; if they cite a **release or tag**, resolve the **commit SHA** (`git rev-parse <tag>^{commit}`) and prefer `git show <SHA>:path` / `git ls-tree` when describing behavior so the report matches that snapshot.
3. **Output path**: default `docs/entrega-<slug>-historias-de-usuario.md` or a path they specify.
4. **Language**: default **Spanish** for section prose and table cells; use another language only if they ask.
5. **Mockups row** in tables: **omit** unless the user explicitly wants mockups attached per card.

## Document structure (use this order)

1. **Title** — e.g. `# Documentación de entrega — <iteración> (<proyecto>)`
2. **Release reference** (if applicable) — link to GitHub release and short line with **tag + commit** and repo link.
3. **`## User stories`** — one subsection per card, **same order as the user’s list** (after dedupe).
4. **`## Resumen ejecutivo`** — bullets: what shipped in scope; call out anything **after** the pinned commit that differs from **current HEAD** if they mixed scope.
5. **`### Decisiones tomadas`** (under resumen or as `##`) — priorities, technical tradeoffs, spikes, tooling, env constraints.
6. **`## Consejos`** (optional, short) — Markdown conventions, verifiable acceptance criteria, linking Trello/GitHub.

## Per user story subsection template

For each Trello URL:

```markdown
### <n>. <Short title>

**Trello:** [<link text>](<exact trello url>)

| Campo | Descripción |
|--------|-------------|
| **Actor(es)** | … |
| **Funcionalidad** | … |
| **Valor** | … |
| **Criterios de aceptación** | … |
```

- **Title**: derive from the Trello URL slug (decode `%…`) or from the card title if the user pasted it; if unclear, use `Historia <n>` and keep the link prominent.
- **Ground truth**: infer **Funcionalidad** and **Criterios de aceptación** from **code, tests, CI, and README** in scope (routes, UI pages, workflows). Run searches and read files; do not invent features.
- **Actor(es)**: who benefits or operates the feature (end user, developer, operator, CI).
- **Valor**: one or two sentences, outcome-focused.

## Quality bar

- **Verifiable acceptance criteria** (commands, endpoints, UI flows, CI job names) over vague wording.
- If the repo **does not implement** a card, state that honestly in that row and separate “planned” from “shipped in scope.”
- **Deduplicate** duplicate Trello links.
- Match **existing project tone** in `docs/` if prior entregas exist.

## Optional intro line (Spanish deliveries)

If the course or stakeholder pack expects it, add under the title:

> A continuación presentamos la documentación que vamos a exigirles en cada entrega.

(Omit if the user says their template does not use it.)

## Reference example in this repo

See `docs/entrega-poc-historias-de-usuario.md` for a completed instance (tables without mockups, resumen ejecutivo, decisiones).
