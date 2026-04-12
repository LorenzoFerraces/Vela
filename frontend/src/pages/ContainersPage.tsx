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

export default function ContainersPage() {
  const [source, setSource] = useState('')
  const [containerName, setContainerName] = useState('')
  const [hostPort, setHostPort] = useState('')
  const [containerPort, setContainerPort] = useState('80')
  const [gitBranch, setGitBranch] = useState('main')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<{ type: 'ok' | 'err'; text: string } | null>(
    null
  )
  const [rows, setRows] = useState<ContainerInfo[]>([])
  const [listLoading, setListLoading] = useState(true)
  const [rowBusy, setRowBusy] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    setListLoading(true)
    setMessage(null)
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
      let host: number | undefined
      if (hostPort.trim() !== '') {
        const parsed = Number.parseInt(hostPort, 10)
        if (Number.isNaN(parsed)) {
          setMessage({ type: 'err', text: 'Host port must be a number.' })
          return
        }
        host = parsed
      }
      const cport = Number.parseInt(containerPort, 10)
      if (Number.isNaN(cport)) {
        setMessage({ type: 'err', text: 'Container port must be a number.' })
        return
      }
      const res = await runContainerFromSource({
        source: trimmed,
        container_name: containerName.trim() || null,
        host_port: host ?? null,
        container_port: cport,
        git_branch: gitBranch.trim() || 'main',
      })
      setMessage({
        type: 'ok',
        text: `Started (${res.kind}) as ${res.container.name} — image ${res.image}`,
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
        Enter a <strong>Docker image</strong> (e.g. <code>nginx:alpine</code>) or a{' '}
        <strong>Git URL</strong> to clone and build with Docker, then run a managed
        container.
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
              Git branch (Git URLs only)
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

        <div className="containers-form__grid containers-form__grid--ports">
          <div>
            <label className="containers-form__label" htmlFor="host-port-input">
              Host port (optional)
            </label>
            <input
              id="host-port-input"
              className="containers-form__input"
              type="text"
              inputMode="numeric"
              value={hostPort}
              onChange={(e) => setHostPort(e.target.value)}
              placeholder="e.g. 18080"
            />
          </div>
          <div>
            <label className="containers-form__label" htmlFor="ctr-port-input">
              Container port
            </label>
            <input
              id="ctr-port-input"
              className="containers-form__input"
              type="text"
              inputMode="numeric"
              value={containerPort}
              onChange={(e) => setContainerPort(e.target.value)}
              placeholder="80"
            />
          </div>
        </div>

        <div className="containers-form__actions">
          <button type="submit" className="btn btn--primary" disabled={busy}>
            {busy ? 'Working…' : 'Pull / build & run'}
          </button>
          <button
            type="button"
            className="btn btn--ghost"
            onClick={() => void refresh()}
            disabled={listLoading || busy}
          >
            Refresh list
          </button>
        </div>
      </form>

      {message && (
        <p
          className={
            message.type === 'ok'
              ? 'containers-banner containers-banner--ok'
              : 'containers-banner containers-banner--err'
          }
          role="alert"
        >
          {message.text}
        </p>
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
