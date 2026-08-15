### Task 11: Deslop + short README note

**Files:**
- Touched implementation files from this feature (deslop only — no behavior change)
- `README.md` — one short bullet on supported languages + manual build override

- [ ] **Step 1: Deslop** — remove unnecessary comments, abnormal try/except, any-casts, deeply nested structure that don't match surrounding code
- [ ] **Step 2: Run focused pytest:** from backend/ `..\..\.venv\Scripts\python.exe -m pytest tests/test_language_detection.py tests/test_dockerfile_templates.py tests/test_ensure_dockerfile.py tests/test_build_override_model.py tests/test_default_image_builder_override.py -q` (venv at f:\lolo\fac\Vela\.venv\Scripts\python.exe)
- [ ] **Step 3: README short note if missing; commit if changed**

```bash
git commit -m "docs: note expanded language detection and build overrides"
```

Keep README concise per AGENTS.md. Do not rewrite unrelated README sections.
