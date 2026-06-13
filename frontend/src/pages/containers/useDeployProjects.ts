import { useEffect, useState } from 'react'
import { formatApiError, listProjects, type Project } from '../../api/client'
import { projectWriteAllowed } from '../../projects/teamDisplay'

function defaultWritableProject(projects: Project[]): Project | undefined {
  const personal = projects.find(
    (project) => project.is_personal && project.role === 'owner'
  )
  return personal ?? projects[0]
}

export function useDeployProjects() {
  const [projects, setProjects] = useState<Project[]>([])
  const [selectedProjectId, setSelectedProjectId] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false

    void (async () => {
      setLoading(true)
      setError(null)
      try {
        const rows = await listProjects()
        if (cancelled) {
          return
        }
        const writable = rows.filter((project) =>
          projectWriteAllowed(project.role)
        )
        setProjects(writable)
        const defaultProject = defaultWritableProject(writable)
        setSelectedProjectId(defaultProject?.id ?? '')
      } catch (loadError) {
        if (!cancelled) {
          setError(formatApiError(loadError))
          setProjects([])
          setSelectedProjectId('')
        }
      } finally {
        if (!cancelled) {
          setLoading(false)
        }
      }
    })()

    return () => {
      cancelled = true
    }
  }, [])

  return {
    projects,
    selectedProjectId,
    setSelectedProjectId,
    loading,
    error,
  }
}
