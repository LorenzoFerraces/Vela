---
globs: "['**/*.tsx', '**/*.ts']"
description: Defines the core structural layout of the React application
  (components, API routes, store).
alwaysApply: true
---

The application follows a strict React architecture: all UI components must reside in `src/components`. API endpoints must be managed within `src/api`. Global state management, including reducers and actions, must use Redux structures located in `src/store`. When writing code, respect this separation of concerns.