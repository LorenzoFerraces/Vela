---
globs: "['backend/tests/**/*.py']"
description: Defines a testing strategy emphasizing full stack integration
  testing for API behavior while limiting unit testing scope to pure domain
  logic.
alwaysApply: true
---

Testing must prioritize integration over mocks. For API behavior, use `TestClient` to exercise the full stack (Route $	o$ Core) using an in-memory database override. Unit tests are restricted only to pure, isolated functions within `app/core/`. Assertions must confirm HTTP responses and persisted state, not mock method calls.