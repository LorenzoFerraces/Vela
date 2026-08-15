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
