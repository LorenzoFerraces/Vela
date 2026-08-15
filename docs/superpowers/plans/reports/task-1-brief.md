### Task 1: Enum, `BuildOverride`, and `NeedsBuildOverrideError`

**Files:**
- Modify: `backend/app/core/enums.py`
- Modify: `backend/app/core/models.py`
- Modify: `backend/app/core/exceptions.py`
- Modify: `backend/app/core/__init__.py` (re-exports if used)
- Test: `backend/tests/test_build_override_model.py`

**Interfaces:**
- Produces: `SupportedLanguage` values `PHP`, `DOTNET`, `ELIXIR`, `CLOJURE`
- Produces: `class BuildOverride(BaseModel)` with fields `language`, `language_version`, `package_manager`, `build_subdir`, `start_command`
- Produces: `NeedsBuildOverrideError` with `code = "needs_build_override"` and `api_response_content()`
- Produces: `ProjectInfo.build_subdir: str | None = None`

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/test_build_override_model.py
from app.core.enums import SupportedLanguage
from app.core.exceptions import NeedsBuildOverrideError
from app.core.models import BuildOverride


def test_supported_language_includes_new_values() -> None:
    assert SupportedLanguage.CLOJURE == "clojure"
    assert SupportedLanguage.PHP == "php"
    assert SupportedLanguage.DOTNET == "dotnet"
    assert SupportedLanguage.ELIXIR == "elixir"


def test_build_override_defaults() -> None:
    override = BuildOverride(language=SupportedLanguage.JAVA)
    assert override.language_version is None
    assert override.package_manager is None
    assert override.build_subdir is None
    assert override.start_command is None


def test_needs_build_override_error_payload() -> None:
    exc = NeedsBuildOverrideError("No Dockerfile and no recognized markers.")
    payload = exc.api_response_content()
    assert payload["code"] == "needs_build_override"
    assert "detail" in payload
```

- [ ] **Step 2: Run test — expect FAIL (missing enum members / types)**

Run: `cd backend && python -m pytest tests/test_build_override_model.py -q`

- [ ] **Step 3: Implement**

In `enums.py` add:

```python
PHP = "php"
DOTNET = "dotnet"
ELIXIR = "elixir"
CLOJURE = "clojure"
```

In `models.py` near `ProjectInfo`:

```python
class BuildOverride(BaseModel):
    language: SupportedLanguage
    language_version: str | None = None
    package_manager: str | None = None
    build_subdir: str | None = None
    start_command: list[str] | None = None
```

Add `build_subdir: str | None = None` to `ProjectInfo`.

In `exceptions.py`:

```python
class NeedsBuildOverrideError(BuilderError):
    """Detection failed; client should collect a BuildOverride via modal."""

    code = "needs_build_override"

    def __init__(self, message: str) -> None:
        super().__init__(message)

    def api_response_content(self) -> dict[str, object]:
        return {"code": self.code, "detail": str(self)}
```

- [ ] **Step 4: Run tests — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/enums.py backend/app/core/models.py backend/app/core/exceptions.py backend/tests/test_build_override_model.py
git commit -m "feat: add BuildOverride model and NeedsBuildOverrideError"
```

Also update `backend/app/core/__init__.py` re-exports if that module exports exceptions/models.
