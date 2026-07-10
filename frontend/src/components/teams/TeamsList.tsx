import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import {
  formatApiError,
  listProjects,
  type Project,
} from '../../api/client'
import { teamDescription, teamDisplayName } from '../../projects/teamDisplay'

type Banner = { tone: 'ok' | 'err'; text: string } | null

function formatRoleLabel(role: string): string {
  return role.charAt(0).toUpperCase() + role.slice(1)
}

export function TeamsList() {
  const { projectId: routeProjectId } = useParams<{ projectId?: string }>()
  const navigate = useNavigate()

  const [projects, setProjects] = useState<Project[]>([])
  const [loading, setLoading] = useState(true)
  const [banner, setBanner] = useState<Banner>(null)
  const [showCreateForm, setShowCreateForm] = useState(false)
  const [newTeamName, setNewTeamName] = useState('')
  const [busy, setBusy] = useState(false)

  const selectedProject = useMemo(() => {
    if (projects.length === 0) {
      return null
    }
    if (routeProjectId) {
      return projects.find((project) => project.id === routeProjectId) ?? projects[0]
    }
    return projects[0]
  }, [projects, routeProjectId])

  const isSelectedOwner = selectedProject?.role === 'owner'

  const loadProjects = useCallback(async () => {
    const projectRows = await listProjects()
    setProjects(projectRows)
    return projectRows
  }, [])

  const refreshProjectsList = useCallback(async () => {
    try {
      await loadProjects()
    } catch (error) {
      setBanner({ tone: 'err', text: formatApiError(error) })
    }
  }, [loadProjects])

  useEffect(() => {
    let cancelled = false

    async function initialLoad() {
      setLoading(true)
      try {
        await loadProjects()
        if (!cancelled) {
          setBanner(null)
        }
      } catch (error) {
        if (!cancelled) {
          setBanner({ tone: 'err', text: formatApiError(error) })
        }
      } finally {
        if (!cancelled) {
          setLoading(false)
        }
      }
    }

    void initialLoad()
    return () => {
      cancelled = true
    }
  }, [loadProjects])

  useEffect(() => {
    if (loading || projects.length === 0) {
      return
    }
    if (!routeProjectId) {
      navigate(`/teams/${projects[0].id}`, { replace: true })
      return
    }
    const exists = projects.some((project) => project.id === routeProjectId)
    if (!exists) {
      navigate(`/teams/${projects[0].id}`, { replace: true })
    }
  }, [loading, projects, routeProjectId, navigate])

  async function onCreateTeam(event: React.FormEvent) {
    event.preventDefault()
    const trimmedName = newTeamName.trim()
    if (!trimmedName) {
      return
    }
    setBusy(true)
    setBanner(null)
    try {
      const created = await createProject(trimmedName)
      setNewTeamName('')
      setShowCreateForm(false)
      setBanner({ tone: 'ok', text: `Team "${created.name}" created.` })
      setProjects((current) => [...current, created])
      navigate(`/teams/${created.id}`)
    } catch (error) {
      setBanner({ tone: 'err', text: formatApiError(error) })
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="teams-page">
      <header className="teams-page__header">
        <div>
          <h1 className="teams-page__title">Teams</h1>
          <p className="teams-page__lead">
            Share container workloads with teammates. Each team has its own members
            and roles.
          </p>
        </div>
        <button
          type="button"
          className="btn btn--primary"
          disabled={busy}
          onClick={() => setShowCreateForm((open) => !open)}
        >
          {showCreateForm ? 'Cancel' : 'Create team'}
        </button>
      </header>

      {banner ? (
        <p
          className={
            banner.tone === 'ok'
              ? 'settings-banner settings-banner--ok'
              : 'settings-banner settings-banner--err'
          }
          role={banner.tone === 'err' ? 'alert' : undefined}
        >
          {banner.text}
        </p>
      ) : null}

      {showCreateForm ? (
        <form className="teams-page__create" onSubmit={onCreateTeam}>
          <label className="teams-page__field teams-page__field--grow">
            Team name
            <input
              type="text"
              className="teams-page__input"
              value={newTeamName}
              disabled={busy}
              onChange={(event) => setNewTeamName(event.target.value)}
              placeholder="My team"
              maxLength={255}
              required
              autoFocus
            />
          </label>
          <button type="submit" className="btn btn--primary" disabled={busy}>
            Create
          </button>
        </form>
      ) : null}

      {loading ? (
        <TeamsPageSkeleton />
      ) : projects.length === 0 ? (
        <p className="teams-page__muted">No teams yet. Create one to get started.</p>
      ) : (
        <div className="teams-page__layout">
          <aside className="teams-page__sidebar">
            <h2 className="teams-page__sidebar-title">Your teams</h2>
            <ul className="teams-page__team-list">
              {projects.map((project) => {
                const isActive = selectedProject?.id === project.id
                return (
                  <li key={project.id}>
                    <Link
                      to={`/teams/${project.id}`}
                      className={
                        isActive
                          ? 'teams-page__team-link teams-page__team-link--active'
                          : 'teams-page__team-link'
                      }
                    >
                      <span className="teams-page__team-name">
                        {teamDisplayName(project)}
                      </span>
                      <span className="teams-page__team-role">
                        {formatRoleLabel(project.role)}
                      </span>
                    </Link>
                  </li>
                )
              })}
            </ul>
          </aside>
        </div>
      )}
    </section>
  )
}