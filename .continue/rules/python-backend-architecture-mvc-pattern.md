---
globs: "['backend/**/*.py']"
description: Enforces MVC separation of concerns within the backend structure
  (Core $	o$ Routes $	o$ Schema).
alwaysApply: true
---

The backend must strictly adhere to an MVC pattern using the following separation of concerns within `backend/app/`: Model (`app/core/`): Domain logic, orchestration, and integrations. Core modules must be stateless. View (`app/api/schemas.py`, route-local models): Defines request/response shapes (the public contract). Controller (`app/api/routes/`): Thin HTTP handlers responsible only for input validation, calling core domain functions, mapping errors, and returning view models. Logic must never reside in the router.