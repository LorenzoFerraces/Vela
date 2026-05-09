import type { GithubRepo } from '../../api/client'
import type { GithubReposCacheState } from './types'

type ContainersGithubRepoPickerPanelProps = {
  githubReposCache: GithubReposCacheState
  filteredRepos: GithubRepo[]
  repoQuery: string
  onRepoQueryChange: (query: string) => void
  onPickRepo: (repo: GithubRepo) => void
}

export function ContainersGithubRepoPickerPanel({
  githubReposCache,
  filteredRepos,
  repoQuery,
  onRepoQueryChange,
  onPickRepo,
}: ContainersGithubRepoPickerPanelProps) {
  return (
    <div
      className="containers-github-picker"
      role="region"
      aria-label="Pick a GitHub repository"
    >
      <input
        type="text"
        className="containers-form__input containers-github-picker__search"
        placeholder="Filter by name, or regex (e.g. ^myorg/)"
        value={repoQuery}
        onChange={(e) => onRepoQueryChange(e.target.value)}
        autoFocus
      />
      {githubReposCache.status === 'loading' ? (
        <p className="containers-github-picker__muted">
          Loading your repositories…
        </p>
      ) : githubReposCache.status === 'error' ? (
        <p className="containers-github-picker__error" role="alert">
          {githubReposCache.detail}
        </p>
      ) : githubReposCache.status === 'ok' &&
        githubReposCache.repos.length === 0 ? (
        <p className="containers-github-picker__muted">
          No repositories returned for this account.
        </p>
      ) : githubReposCache.status === 'ok' && filteredRepos.length === 0 ? (
        <p className="containers-github-picker__muted">
          No repositories match this filter.
        </p>
      ) : githubReposCache.status === 'ok' ? (
        <ul className="containers-github-picker__list">
          {filteredRepos.map((repo) => (
            <li key={repo.full_name} className="containers-github-picker__item">
              <div className="containers-github-picker__meta">
                <span className="containers-github-picker__name">
                  {repo.full_name}
                </span>
                {repo.private ? (
                  <span className="containers-github-picker__badge">Private</span>
                ) : null}
                <span className="containers-github-picker__branch">
                  default: {repo.default_branch || 'main'}
                </span>
              </div>
              <button
                type="button"
                className="btn btn--ghost btn--sm"
                onClick={() => onPickRepo(repo)}
              >
                Use
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  )
}
