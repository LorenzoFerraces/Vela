import { useCallback, useEffect, useState } from 'react'
import {
  ApiError,
  type ContainerInfo,
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

function formatApiError(e: unknown): string {
  if (e instanceof ApiError) {
    try {
      const j = JSON.parse(e.body) as { detail?: string; build_log?: string }
      const detail = j.detail ?? e.message
      if (j.build_log) {
        return `${detail}\n\n${j.build_log.slice(-2000)}`
      }
      return detail
    } catch {
      return e.message
    }
  }
  return String(e)
}

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
  const [source, setSource] = useState('')
  const [containerName, setContainerName] = useState('')
  const [gitBranch, setGitBranch] = useState('main')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<FormMessage | null>(null)
  const [rows, setRows] = useState<ContainerInfo[]>([])
  const [listLoading, setListLoading] = useState(true)
  const [rowBusy, setRowBusy] = useState<string | null>(null)

  const showGitBranch = sourceLooksLikeGitUrl(source)

  const refresh = useCallback(async () => {
    setListLoading(true)
    try {
      const data = await listContainers()
      setRows(data)
    } catch (e) {
      setMessage({ type: 'err', text: formatApiError(e) })
    } finally {
      setListLoading(false)
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault()
    const trimmed = source.trim()
    if (!trimmed) {
      setMessage({ type: 'err', text: 'Enter a Docker image or a Git URL.' })
      return
    }
    setBusy(true)
    setMessage(null)
    try {
      const res = await runContainerFromSource({
        source: trimmed,
        container_name: containerName.trim() || null,
        host_port: null,
        container_port: 80,
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
    } catch (err) {
      setMessage({ type: 'err', text: formatApiError(err) })
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
    } catch (err) {
      setMessage({ type: 'err', text: formatApiError(err) })
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
    } catch (err) {
      setMessage({ type: 'err', text: formatApiError(err) })
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
    } catch (err) {
      setMessage({ type: 'err', text: formatApiError(err) })
    } finally {
      setRowBusy(null)
    }
  }

  return (
    <section className="containers-page">
      <h1 className="containers-page__title">Containers</h1>
      <p className="containers-page__lead">
        Image or Git URL → build and run on the Vela network. Public URL uses{' '}
        <code className="containers-form__code">VELA_PUBLIC_ROUTE_DOMAIN</code> (see README).
      </p>

      <form className="containers-form" onSubmit={onSubmit}>
        <label className="containers-form__label" htmlFor="source-input">
          Image or Git URL
        </label>
        <input
          id="source-input"
          className="containers-form__input"
          type="text"
          autoComplete="off"
          placeholder="nginx:alpine or https://github.com/org/repo.git"
          value={source}
          onChange={(e) => setSource(e.target.value)}
          aria-label="Docker image reference or Git clone URL"
        />

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
          </>
        )}

        <div className="containers-form__actions">
          <button type="submit" className="btn btn--primary" disabled={busy}>
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
