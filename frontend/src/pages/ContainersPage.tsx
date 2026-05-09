import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useAuth } from '../auth/AuthContext'
import {
  type ContainerInfo,
  type GithubRepo,
  type GithubStatus,
  fetchAllGithubRepos,
  filterGithubReposByQuery,
  formatApiError,
  getGithubStatusWithRetry,
  getImageAvailability,
  listContainers,
  removeContainer,
  runContainerFromSource,
  startContainer,
  stopContainer,
} from '../api/client'

type FormMessage = {
  type: 'ok' | 'err'
  text: string
  publicUrl?: string
}

type GithubReposCacheState =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'ok'; repos: GithubRepo[] }
  | { status: 'error'; detail: string }

type ImageRefCheckState =
  | { status: 'idle' }
  | { status: 'checking' }
  | { status: 'ok'; ref: string }
  | {
      status: 'unavailable'
      ref: string
      /** When true, registry returned 401/403; user may still try Build after `docker login`. */
      canAttemptDeploy: boolean
    }
  | { status: 'error'; detail: string }

const IMAGE_REF_CHECK_DEBOUNCE_MS = 600

/** Matches backend `_infer_source_kind` in `app/api/routes/containers.py`. */
function sourceLooksLikeGitUrl(source: string): boolean {
  const trimmed = source.trim()
  return (
    trimmed.startsWith('git@') ||
    trimmed.startsWith('http://') ||
    trimmed.startsWith('https://') ||
    trimmed.startsWith('ssh://')
  )
}

export default function ContainersPage() {
  const { user, status: authStatus } = useAuth()
  const [source, setSource] = useState('')
  const [containerName, setContainerName] = useState('')
  const [gitBranch, setGitBranch] = useState('main')
  /** App listen port inside the container (Traefik target when not publishing host ports). */
  const [containerPort, setContainerPort] = useState('80')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<FormMessage | null>(null)
  const [rows, setRows] = useState<ContainerInfo[]>([])
  const [listLoading, setListLoading] = useState(true)
  const [rowBusy, setRowBusy] = useState<string | null>(null)
  const [imageRefCheck, setImageRefCheck] = useState<ImageRefCheckState>({
    status: 'idle',
  })
  const [githubStatus, setGithubStatus] = useState<GithubStatus | null>(null)
  const [githubReposCache, setGithubReposCache] = useState<GithubReposCacheState>({
    status: 'idle',
  })
  const [repoPickerOpen, setRepoPickerOpen] = useState(false)
  const [repoQuery, setRepoQuery] = useState('')
  const sourceTrimmedRef = useRef('')
  sourceTrimmedRef.current = source.trim()

  const showGitBranch = sourceLooksLikeGitUrl(source)

  useEffect(() => {
    if (showGitBranch) {
      setContainerPort((p) => (p === '80' ? '5173' : p))
    } else {
      setContainerPort((p) => (p === '5173' ? '80' : p))
    }
  }, [showGitBranch])

  const refresh = useCallback(async () => {
    setListLoading(true)
    try {
      const data = await listContainers()
      setRows(data)
    } catch (error) {
      setMessage({ type: 'err', text: formatApiError(error) })
    } finally {
      setListLoading(false)
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  useEffect(() => {
    let cancelled = false
    void (async () => {
      if (authStatus !== 'authenticated' || !user?.id) {
        return
      }
      try {
        const status = await getGithubStatusWithRetry()
        if (!cancelled) setGithubStatus(status)
      } catch {
        if (!cancelled) {
          setGithubStatus({
            connected: false,
            login: null,
            avatar_url: null,
            scopes: [],
            connected_at: null,
          })
        }
      }
    })()
    return () => {
      cancelled = true
    }
  }, [authStatus, user?.id])

  useEffect(() => {
    function onVisible() {
      if (document.visibilityState !== 'visible') return
      if (authStatus !== 'authenticated' || !user?.id) return
      void getGithubStatusWithRetry()
        .then(setGithubStatus)
        .catch(() => {
          setGithubStatus({
            connected: false,
            login: null,
            avatar_url: null,
            scopes: [],
            connected_at: null,
          })
        })
    }
    document.addEventListener('visibilitychange', onVisible)
    return () => {
      document.removeEventListener('visibilitychange', onVisible)
    }
  }, [authStatus, user?.id])

  useEffect(() => {
    let cancelled = false
    if (!githubStatus?.connected) {
      setGithubReposCache({ status: 'idle' })
      return () => {
        cancelled = true
      }
    }
    setGithubReposCache({ status: 'loading' })
    void fetchAllGithubRepos()
      .then((repos) => {
        if (!cancelled) {
          setGithubReposCache({ status: 'ok', repos })
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setGithubReposCache({
            status: 'error',
            detail: formatApiError(error),
          })
        }
      })
    return () => {
      cancelled = true
    }
  }, [githubStatus?.connected])

  const filteredGithubRepos = useMemo(() => {
    if (githubReposCache.status !== 'ok') {
      return []
    }
    return filterGithubReposByQuery(githubReposCache.repos, repoQuery)
  }, [githubReposCache, repoQuery])

  function toggleRepoPicker() {
    if (repoPickerOpen) {
      setRepoPickerOpen(false)
      setRepoQuery('')
      return
    }
    setRepoPickerOpen(true)
  }

  function pickRepo(repo: GithubRepo) {
    setSource(`${repo.html_url}.git`)
    setGitBranch(repo.default_branch || 'main')
    setImageRefCheck({ status: 'idle' })
    setRepoPickerOpen(false)
    setRepoQuery('')
  }

  const runImageRefAvailabilityCheck = useCallback(async (ref: string) => {
    setImageRefCheck({ status: 'checking' })
    try {
      const result = await getImageAvailability(ref)
      if (sourceTrimmedRef.current !== ref) {
        return
      }
      if (!result.checked) {
        setImageRefCheck({ status: 'idle' })
        return
      }
      if (result.available) {
        setImageRefCheck({ status: 'ok', ref: result.ref })
      } else {
        setImageRefCheck({
          status: 'unavailable',
          ref: result.ref,
          canAttemptDeploy: result.can_attempt_deploy === true,
        })
      }
    } catch (error) {
      if (sourceTrimmedRef.current !== ref) {
        return
      }
      setImageRefCheck({
        status: 'error',
        detail: formatApiError(error),
      })
    }
  }, [])

  useEffect(() => {
    const trimmed = source.trim()
    if (!trimmed || sourceLooksLikeGitUrl(trimmed)) {
      setImageRefCheck({ status: 'idle' })
      return
    }
    const handle = window.setTimeout(() => {
      void runImageRefAvailabilityCheck(trimmed)
    }, IMAGE_REF_CHECK_DEBOUNCE_MS)
    return () => {
      window.clearTimeout(handle)
    }
  }, [source, runImageRefAvailabilityCheck])

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault()
    const trimmed = source.trim()
    if (!trimmed) {
      setMessage({ type: 'err', text: 'Enter a Docker image or a Git URL.' })
      return
    }
    if (!sourceLooksLikeGitUrl(trimmed)) {
      const alreadyOkForRef =
        imageRefCheck.status === 'ok' && imageRefCheck.ref === trimmed
      if (!alreadyOkForRef) {
        try {
          const availability = await getImageAvailability(trimmed)
          if (availability.checked && !availability.available) {
            const notFoundMessage = 'Image not found.'
            setImageRefCheck({
              status: 'unavailable',
              ref: availability.ref,
              canAttemptDeploy: availability.can_attempt_deploy === true,
            })
            setMessage({ type: 'err', text: notFoundMessage })
            return
          }
          if (availability.checked && availability.available) {
            setImageRefCheck({ status: 'ok', ref: availability.ref })
          }
        } catch (error) {
          setMessage({ type: 'err', text: formatApiError(error) })
          return
        }
      }
    }
    setBusy(true)
    setMessage(null)
    try {
      const parsedPort = parseInt(containerPort.trim(), 10)
      const container_port = Number.isNaN(parsedPort)
        ? showGitBranch
          ? 5173
          : 80
        : parsedPort
      const res = await runContainerFromSource({
        source: trimmed,
        container_name: containerName.trim() || null,
        host_port: null,
        container_port,
        git_branch: gitBranch.trim() || 'main',
        route_host: null,
        route_path_prefix: '/',
        route_tls: false,
        public_route: true,
      })
      const routeNote = res.route_wired
        ? ' Traefik route registered.'
        : ''
      const publicUrl =
        typeof res.public_url === 'string' && res.public_url.length > 0
          ? res.public_url
          : undefined
      setMessage({
        type: 'ok',
        text: `Started (${res.kind}) as ${res.container.name} — image ${res.image}.${routeNote}`,
        publicUrl,
      })
      setSource('')
      await refresh()
    } catch (error) {
      setMessage({ type: 'err', text: formatApiError(error) })
    } finally {
      setBusy(false)
    }
  }

  async function onStart(id: string) {
    setRowBusy(id)
    setMessage(null)
    try {
      await startContainer(id)
      await refresh()
    } catch (error) {
      setMessage({ type: 'err', text: formatApiError(error) })
    } finally {
      setRowBusy(null)
    }
  }

  async function onStop(id: string) {
    setRowBusy(id)
    setMessage(null)
    try {
      await stopContainer(id)
      await refresh()
    } catch (error) {
      setMessage({ type: 'err', text: formatApiError(error) })
    } finally {
      setRowBusy(null)
    }
  }

  async function onRemove(id: string) {
    if (!window.confirm('Remove this container?')) return
    setRowBusy(id)
    setMessage(null)
    try {
      await removeContainer(id, true)
      await refresh()
    } catch (error) {
      setMessage({ type: 'err', text: formatApiError(error) })
    } finally {
      setRowBusy(null)
    }
  }

  return (
    <section className="containers-page">
      <h1 className="containers-page__title">Containers</h1>
      <p className="containers-page__lead">
        Image or Git URL → build and run on the Vela network.
      </p>

      <form className="containers-form" onSubmit={onSubmit}>
        <div className="containers-form__source-header">
          <label className="containers-form__label" htmlFor="source-input">
            Image or Git URL
          </label>
          {githubStatus?.connected ? (
            <button
              type="button"
              className="btn btn--ghost btn--sm"
              onClick={toggleRepoPicker}
            >
              {repoPickerOpen ? 'Hide picker' : 'Pick from GitHub'}
            </button>
          ) : null}
        </div>
        {repoPickerOpen ? (
          <div className="containers-github-picker" role="region" aria-label="Pick a GitHub repository">
            <input
              type="text"
              className="containers-form__input containers-github-picker__search"
              placeholder="Filter by name, or regex (e.g. ^myorg/)"
              value={repoQuery}
              onChange={(e) => setRepoQuery(e.target.value)}
              autoFocus
            />
            {githubReposCache.status === 'loading' ? (
              <p className="containers-github-picker__muted">Loading your repositories…</p>
            ) : githubReposCache.status === 'error' ? (
              <p className="containers-github-picker__error" role="alert">
                {githubReposCache.detail}
              </p>
            ) : githubReposCache.status === 'ok' && githubReposCache.repos.length === 0 ? (
              <p className="containers-github-picker__muted">
                No repositories returned for this account.
              </p>
            ) : githubReposCache.status === 'ok' && filteredGithubRepos.length === 0 ? (
              <p className="containers-github-picker__muted">
                No repositories match this filter.
              </p>
            ) : githubReposCache.status === 'ok' ? (
              <ul className="containers-github-picker__list">
                {filteredGithubRepos.map((repo) => (
                  <li key={repo.full_name} className="containers-github-picker__item">
                    <div className="containers-github-picker__meta">
                      <span className="containers-github-picker__name">{repo.full_name}</span>
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
                      onClick={() => pickRepo(repo)}
                    >
                      Use
                    </button>
                  </li>
                ))}
              </ul>
            ) : null}
          </div>
        ) : null}
        <input
          id="source-input"
          className="containers-form__input"
          type="text"
          autoComplete="off"
          placeholder="nginx:alpine or https://github.com/org/repo.git"
          value={source}
          onChange={(e) => setSource(e.target.value)}
          onBlur={() => {
            const trimmed = source.trim()
            if (trimmed && !sourceLooksLikeGitUrl(trimmed)) {
              void runImageRefAvailabilityCheck(trimmed)
            }
          }}
          aria-label="Docker image reference or Git clone URL"
          aria-invalid={
            !showGitBranch && imageRefCheck.status === 'unavailable'
              ? true
              : undefined
          }
          aria-describedby={
            !showGitBranch && imageRefCheck.status !== 'idle'
              ? 'source-input-status'
              : undefined
          }
        />
        {!showGitBranch && imageRefCheck.status === 'checking' ? (
          <p
            id="source-input-status"
            className="containers-source-check containers-source-check--muted"
          >
            Checking registry…
          </p>
        ) : null}
        {!showGitBranch && imageRefCheck.status === 'ok' ? (
          <p
            id="source-input-status"
            className="containers-source-check containers-source-check--ok"
          >
            Image reference found.
          </p>
        ) : null}
        {!showGitBranch && imageRefCheck.status === 'unavailable' ? (
          <p
            id="source-input-status"
            className={
              imageRefCheck.canAttemptDeploy
                ? 'containers-source-check containers-source-check--warn'
                : 'containers-source-check containers-source-check--err'
            }
            role="alert"
          >
            Image not found.
          </p>
        ) : null}
        {!showGitBranch && imageRefCheck.status === 'error' ? (
          <p
            id="source-input-status"
            className="containers-source-check containers-source-check--warn"
            role="alert"
          >
            Could not verify image: {imageRefCheck.detail}
          </p>
        ) : null}

        {showGitBranch ? (
          <div className="containers-form__grid">
            <div>
              <label className="containers-form__label" htmlFor="name-input">
                Container name (optional)
              </label>
              <input
                id="name-input"
                className="containers-form__input"
                type="text"
                value={containerName}
                onChange={(e) => setContainerName(e.target.value)}
                placeholder="my-service"
              />
            </div>
            <div>
              <label className="containers-form__label" htmlFor="branch-input">
                Git branch
              </label>
              <input
                id="branch-input"
                className="containers-form__input"
                type="text"
                value={gitBranch}
                onChange={(e) => setGitBranch(e.target.value)}
                placeholder="main"
              />
            </div>
            <div>
              <label
                className="containers-form__label"
                htmlFor="container-port-input"
              >
                Container port
              </label>
              <input
                id="container-port-input"
                className="containers-form__input"
                type="number"
                min={1}
                max={65535}
                value={containerPort}
                onChange={(e) => setContainerPort(e.target.value)}
                placeholder="5173"
                aria-describedby="container-port-hint"
              />
              <p id="container-port-hint" className="containers-muted containers-form__hint">
                Must match the dev server port (e.g. Vite 5173, or{' '}
                <code>server.port</code> in vite.config).
              </p>
            </div>
          </div>
        ) : (
          <>
            <label className="containers-form__label" htmlFor="name-input">
              Container name (optional)
            </label>
            <input
              id="name-input"
              className="containers-form__input"
              type="text"
              value={containerName}
              onChange={(e) => setContainerName(e.target.value)}
              placeholder="my-service"
            />
            <label
              className="containers-form__label"
              htmlFor="container-port-input"
            >
              Container port
            </label>
            <input
              id="container-port-input"
              className="containers-form__input"
              type="number"
              min={1}
              max={65535}
              value={containerPort}
              onChange={(e) => setContainerPort(e.target.value)}
              placeholder="80"
              aria-describedby="container-port-hint-image"
            />
            <p
              id="container-port-hint-image"
              className="containers-muted containers-form__hint"
            >
              Port your app listens on inside the container (Traefik target when using a
              public URL without host port publish).
            </p>
          </>
        )}

        <div className="containers-form__actions">
          <button
            type="submit"
            className="btn btn--primary"
            disabled={
              busy ||
              (!showGitBranch && imageRefCheck.status === 'unavailable')
            }
          >
            {busy ? 'Building…' : 'Build'}
          </button>
          <button
            type="button"
            className="btn btn--ghost"
            onClick={() => {
              setMessage(null)
              void refresh()
            }}
            disabled={listLoading || busy}
          >
            Refresh list
          </button>
        </div>
      </form>

      {message && (
        <div
          className={
            message.type === 'ok'
              ? 'containers-banner containers-banner--ok'
              : 'containers-banner containers-banner--err'
          }
          role="alert"
        >
          <p className="containers-banner__text">{message.text}</p>
          {message.type === 'ok' && message.publicUrl ? (
            <div className="containers-public-url">
              <a
                className="containers-public-url__link"
                href={message.publicUrl}
                target="_blank"
                rel="noreferrer"
              >
                {message.publicUrl}
              </a>
              <button
                type="button"
                className="btn btn--ghost btn--sm"
                onClick={() => void navigator.clipboard.writeText(message.publicUrl!)}
              >
                Copy URL
              </button>
            </div>
          ) : null}
        </div>
      )}

      <h2 className="containers-page__subtitle">Running workloads</h2>
      {listLoading && rows.length === 0 ? (
        <p className="containers-muted">Loading…</p>
      ) : rows.length === 0 ? (
        <p className="containers-muted">No Vela-managed containers yet.</p>
      ) : (
        <div className="containers-table-wrap">
          <table className="containers-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Image</th>
                <th>Status</th>
                <th>Ports</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((c) => (
                <tr key={c.id}>
                  <td>{c.name}</td>
                  <td className="containers-table__mono">{c.image}</td>
                  <td>
                    <span className="containers-status">{c.status}</span>
                  </td>
                  <td className="containers-table__ports">
                    {c.ports.length === 0
                      ? '—'
                      : c.ports
                          .map(
                            (p) =>
                              `${p.host_port}:${p.container_port}/${p.protocol}`
                          )
                          .join(', ')}
                  </td>
                  <td className="containers-table__actions">
                    <button
                      type="button"
                      className="btn btn--sm btn--ghost"
                      disabled={
                        rowBusy === c.id || c.status === 'running'
                      }
                      onClick={() => void onStart(c.id)}
                    >
                      Start
                    </button>
                    <button
                      type="button"
                      className="btn btn--sm btn--ghost"
                      disabled={
                        rowBusy === c.id || c.status !== 'running'
                      }
                      onClick={() => void onStop(c.id)}
                    >
                      Stop
                    </button>
                    <button
                      type="button"
                      className="btn btn--sm btn--danger"
                      disabled={rowBusy === c.id}
                      onClick={() => void onRemove(c.id)}
                    >
                      Remove
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
