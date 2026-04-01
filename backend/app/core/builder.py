from abc import ABC, abstractmethod

from app.core.models import BuildResult, ProjectInfo, ProjectSource


class ImageBuilder(ABC):
    """Provider-agnostic interface for turning source code into container images.

    The hybrid strategy (Dockerfile templates first, buildpacks as fallback)
    is an implementation detail of concrete adapters — this interface is
    strategy-agnostic.  The ``build_from_source`` method is the primary
    entry-point for consumers; the remaining methods expose individual
    pipeline stages for fine-grained control.
    """

    @abstractmethod
    async def build_from_source(
        self, source: ProjectSource, *, tag: str
    ) -> BuildResult:
        """Full pipeline: clone → analyse → generate/detect Dockerfile → build.

        This is the single method most consumers should call.  Concrete
        implementations decide whether to use an existing Dockerfile,
        generate one from a template, or fall back to buildpacks.

        Args:
            source: Git URL or local path to the project.
            tag:    Image tag to assign to the built image.

        Returns:
            A ``BuildResult`` with the image ID, tag, strategy used, and
            build log.
        """

    @abstractmethod
    async def analyze(self, project_path: str) -> ProjectInfo:
        """Inspect a local project directory and detect its characteristics.

        Detection should cover at minimum:
        - Programming language (via marker files like ``requirements.txt``,
          ``package.json``, ``go.mod``, etc.)
        - Framework (if recognisable from dependency declarations)
        - Entrypoint file
        - Whether a Dockerfile already exists
        """

    @abstractmethod
    async def generate_dockerfile(
        self, project_path: str, project_info: ProjectInfo
    ) -> str:
        """Generate Dockerfile contents for the analysed project.

        Returns:
            The Dockerfile content as a string.

        Raises:
            UnsupportedLanguageError: If no template exists for the detected
                language.
        """

    @abstractmethod
    async def clone_repository(
        self, git_url: str, *, branch: str = "main"
    ) -> str:
        """Clone a remote git repository into a temporary directory.

        Returns:
            The absolute path to the cloned project on the local filesystem.
        """
