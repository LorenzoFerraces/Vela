import type { BuildOverride, BuildOverrideLanguage } from '../../api/client'

export const BUILD_OVERRIDE_LANGUAGES: readonly BuildOverrideLanguage[] = [
  'python',
  'javascript',
  'typescript',
  'go',
  'java',
  'rust',
  'ruby',
  'php',
  'dotnet',
  'elixir',
  'clojure',
] as const

export type PackageManagerOption = {
  value: string
  label: string
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

function hasStringBody(error: unknown): error is { body: string } {
  return isRecord(error) && typeof error.body === 'string'
}

/** True when an API failure asks the client to collect a BuildOverride. */
export function isNeedsBuildOverrideError(error: unknown): boolean {
  if (!hasStringBody(error)) {
    return false
  }
  try {
    const parsed: unknown = JSON.parse(error.body)
    return (
      isRecord(parsed) &&
      parsed.code === 'needs_build_override'
    )
  } catch {
    return false
  }
}

export function isBuildOverrideLanguage(
  value: string,
): value is BuildOverrideLanguage {
  return (BUILD_OVERRIDE_LANGUAGES as readonly string[]).includes(value)
}

export function packageManagersForLanguage(
  language: BuildOverrideLanguage,
): PackageManagerOption[] {
  switch (language) {
    case 'java':
      return [
        { value: 'gradle', label: 'Gradle' },
        { value: 'maven', label: 'Maven' },
      ]
    case 'javascript':
    case 'typescript':
      return [
        { value: 'npm', label: 'npm' },
        { value: 'pnpm', label: 'pnpm' },
        { value: 'yarn', label: 'Yarn' },
      ]
    case 'clojure':
      return [
        { value: 'deps', label: 'Clojure CLI (deps.edn)' },
        { value: 'lein', label: 'Leiningen' },
      ]
    case 'python':
    case 'go':
    case 'rust':
    case 'ruby':
    case 'php':
    case 'dotnet':
    case 'elixir':
      return []
    default: {
      const _exhaustive: never = language
      return _exhaustive
    }
  }
}

export function defaultPackageManager(
  language: BuildOverrideLanguage,
): string | null {
  const options = packageManagersForLanguage(language)
  return options[0]?.value ?? null
}

export function defaultLanguageVersion(
  language: BuildOverrideLanguage,
): string {
  switch (language) {
    case 'python':
      return '3.12'
    case 'javascript':
    case 'typescript':
      return '20'
    case 'go':
      return '1.22'
    case 'java':
    case 'clojure':
      return '21'
    case 'rust':
      return '1.75'
    case 'ruby':
      return '3.3'
    case 'php':
      return '8.3'
    case 'dotnet':
      return '8.0'
    case 'elixir':
      return '1.16'
    default: {
      const _exhaustive: never = language
      return _exhaustive
    }
  }
}

export function languageLabel(language: BuildOverrideLanguage): string {
  switch (language) {
    case 'python':
      return 'Python'
    case 'javascript':
      return 'JavaScript'
    case 'typescript':
      return 'TypeScript'
    case 'go':
      return 'Go'
    case 'java':
      return 'Java'
    case 'rust':
      return 'Rust'
    case 'ruby':
      return 'Ruby'
    case 'php':
      return 'PHP'
    case 'dotnet':
      return '.NET'
    case 'elixir':
      return 'Elixir'
    case 'clojure':
      return 'Clojure'
    default: {
      const _exhaustive: never = language
      return _exhaustive
    }
  }
}

export function parseStartCommand(value: string): string[] | null {
  const trimmed = value.trim()
  if (!trimmed) {
    return null
  }
  return trimmed.split(/\s+/).filter(Boolean)
}

export function formatStartCommand(command: string[] | null | undefined): string {
  return (command ?? []).join(' ')
}

export function emptyBuildOverride(
  language: BuildOverrideLanguage = 'python',
): BuildOverride {
  return {
    language,
    language_version: defaultLanguageVersion(language),
    package_manager: defaultPackageManager(language),
    build_subdir: null,
    start_command: null,
  }
}

export function normalizeBuildOverride(override: BuildOverride): BuildOverride {
  const languageVersion = override.language_version?.trim() || null
  const buildSubdir = override.build_subdir?.trim() || null
  const packageManagers = packageManagersForLanguage(override.language)
  const packageManager =
    packageManagers.length === 0
      ? null
      : override.package_manager &&
          packageManagers.some((option) => option.value === override.package_manager)
        ? override.package_manager
        : defaultPackageManager(override.language)
  const startCommand =
    override.start_command && override.start_command.length > 0
      ? override.start_command
      : null

  return {
    language: override.language,
    language_version: languageVersion,
    package_manager: packageManager,
    build_subdir: buildSubdir,
    start_command: startCommand,
  }
}
