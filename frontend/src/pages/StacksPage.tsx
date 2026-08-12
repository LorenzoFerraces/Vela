import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  deleteStack,
  deployStack,
  formatApiError,
  getStack,
  listStacks,
  updateStack,
  type BuildOverride,
  type Stack,
  type StackService,
  type StackServiceCreate,
} from '../api/client'
import BuildConfigModal from './containers/BuildConfigModal'
import {
  isNeedsBuildOverrideError,
  parseFailedServiceNameFromError,
} from './containers/buildOverride'

type Banner = { tone: 'ok' | 'err'; text: string } | null

function stackServiceToCreate(service: StackService): StackServiceCreate {
  return {
    service_name: service.service_name,
    source_kind: service.source_kind,
    source_ref: service.source_ref,
    git_branch: service.git_branch,
    container_port: service.container_port,
    env_vars: service.env_vars,
    command: service.command,
    public_route: service.public_route,
    depends_on: service.depends_on,
    volumes: service.volumes,
    scaling_policy: service.scaling_policy,
    build_override: service.build_override ?? null,
  }
}

function resolveFailedService(
  stack: Stack,
  failedServiceName: string | null,
): StackService | null {
  if (failedServiceName) {
    const named = stack.services.find(
      (service) => service.service_name === failedServiceName,
    )
    if (named) {
      return named
    }
  }
  return (
    stack.services.find(
      (service) => service.source_kind === 'git' && !service.build_override,
    ) ??
    stack.services.find((service) => service.source_kind === 'git') ??
    null
  )
}

function StackRow({
  stack,
  busy,
  pendingDelete,
  onDeploy,
  onDelete,
  onEdit,
}: {
  stack: Stack
  busy: boolean
  pendingDelete: string | null
  onDeploy: (id: string) => void
  onDelete: (id: string) => void
  onEdit: (id: string) => void
}) {
  const isPending = pendingDelete === stack.id
  return (
    <tr key={stack.id}>
      <td>{stack.name}</td>
      <td className="containers-table__mono">{stack.network_name}</td>
      <td>{stack.services.length}</td>
      <td className="containers-muted">
        {new Date(stack.created_at).toLocaleDateString()}
      </td>
      <td className="containers-table__actions">
        <button
          type="button"
          className="btn btn--ghost btn--sm"
          onClick={() => onEdit(stack.id)}
        >
          Edit
        </button>
        <button
          type="button"
          className="btn btn--ghost btn--sm"
          onClick={() => onDeploy(stack.id)}
          disabled={busy}
        >
          Deploy
        </button>
        <button
          type="button"
          className="btn btn--danger btn--sm"
          onClick={() => onDelete(stack.id)}
          disabled={busy}
        >
          {isPending ? 'Confirm?' : 'Remove'}
        </button>
      </td>
    </tr>
  )
}

export default function StacksPage() {
  const navigate = useNavigate()
  const [stacks, setStacks] = useState<Stack[]>([])
  const [listLoading, setListLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [banner, setBanner] = useState<Banner>(null)
  const [pendingDelete, setPendingDelete] = useState<string | null>(null)
  const [buildConfigOpen, setBuildConfigOpen] = useState(false)
  const [buildConfigInitial, setBuildConfigInitial] = useState<BuildOverride | null>(
    null,
  )
  const [pendingDeployStackId, setPendingDeployStackId] = useState<string | null>(
    null,
  )
  const [pendingServiceName, setPendingServiceName] = useState<string | null>(null)
  const deleteTimer = useRef<ReturnType<typeof setTimeout>>(undefined)

  const loadStacks = useCallback(async () => {
    try {
      const rows = await listStacks()
      setStacks(rows)
    } catch (err) {
      setBanner({ tone: 'err', text: formatApiError(err) })
    } finally {
      setListLoading(false)
    }
  }, [])

  useEffect(() => {
    loadStacks()
  }, [loadStacks])

  useEffect(() => {
    return () => {
      if (deleteTimer.current) clearTimeout(deleteTimer.current)
    }
  }, [])

  const openBuildConfigForDeployFailure = useCallback(
    async (stackId: string, error: unknown) => {
      try {
        const stack = await getStack(stackId)
        const failedName = parseFailedServiceNameFromError(error)
        const service = resolveFailedService(stack, failedName)
        if (!service) {
          setBanner({
            tone: 'err',
            text: formatApiError(error),
          })
          return
        }
        setPendingDeployStackId(stackId)
        setPendingServiceName(service.service_name)
        setBuildConfigInitial(service.build_override ?? null)
        setBuildConfigOpen(true)
        setBanner({
          tone: 'err',
          text: `Build config needed for service '${service.service_name}'.`,
        })
      } catch (loadError) {
        setBanner({ tone: 'err', text: formatApiError(loadError) })
      }
    },
    [],
  )

  const handleDeploy = useCallback(
    async (id: string) => {
      setBusy(true)
      setBanner(null)
      try {
        await deployStack(id)
        setBanner({ tone: 'ok', text: 'Stack deployed.' })
        await loadStacks()
      } catch (err) {
        if (isNeedsBuildOverrideError(err)) {
          await openBuildConfigForDeployFailure(id, err)
          return
        }
        setBanner({ tone: 'err', text: formatApiError(err) })
      } finally {
        setBusy(false)
      }
    },
    [loadStacks, openBuildConfigForDeployFailure],
  )

  function closeBuildConfigModal() {
    setBuildConfigOpen(false)
    setPendingDeployStackId(null)
    setPendingServiceName(null)
    setBuildConfigInitial(null)
  }

  async function onBuildConfigConfirm(override: BuildOverride) {
    const stackId = pendingDeployStackId
    const serviceName = pendingServiceName
    closeBuildConfigModal()
    if (!stackId || !serviceName) {
      return
    }

    setBusy(true)
    setBanner(null)
    try {
      const stack = await getStack(stackId)
      const services = stack.services.map((service) => {
        const create = stackServiceToCreate(service)
        if (service.service_name === serviceName) {
          return { ...create, build_override: override }
        }
        return create
      })
      await updateStack(stackId, {
        name: stack.name,
        services,
      })
      await deployStack(stackId)
      setBanner({ tone: 'ok', text: 'Stack deployed.' })
      await loadStacks()
    } catch (err) {
      if (isNeedsBuildOverrideError(err)) {
        await openBuildConfigForDeployFailure(stackId, err)
        return
      }
      setBanner({ tone: 'err', text: formatApiError(err) })
    } finally {
      setBusy(false)
    }
  }

  const handleDelete = useCallback(async (id: string) => {
    if (pendingDelete === id) {
      setPendingDelete(null)
      if (deleteTimer.current) clearTimeout(deleteTimer.current)
      setBusy(true)
      setBanner(null)
      try {
        await deleteStack(id)
        setStacks((prev) => prev.filter((s) => s.id !== id))
        setBanner({ tone: 'ok', text: 'Stack deleted.' })
      } catch (err) {
        setBanner({ tone: 'err', text: formatApiError(err) })
      } finally {
        setBusy(false)
      }
    } else {
      setPendingDelete(id)
      if (deleteTimer.current) clearTimeout(deleteTimer.current)
      deleteTimer.current = setTimeout(() => setPendingDelete(null), 5000)
    }
  }, [pendingDelete])

  return (
    <section className="stacks-page">
      <h1 className="containers-page__title">Stacks</h1>
      <p className="containers-page__lead">
        Multi-app stacks — group services on a shared network.
      </p>

      <div className="stacks-page__actions">
        <button
          type="button"
          className="btn btn--primary"
          onClick={() => navigate('/stacks/new')}
        >
          New Stack
        </button>
        <button
          type="button"
          className="btn btn--ghost"
          onClick={() => navigate('/stacks/import')}
        >
          Import Compose
        </button>
      </div>

      {banner ? (
        <div
          className={
            banner.tone === 'ok'
              ? 'containers-banner containers-banner--ok'
              : 'containers-banner containers-banner--err'
          }
          role={banner.tone === 'err' ? 'alert' : undefined}
        >
          <p className="containers-banner__text">{banner.text}</p>
        </div>
      ) : null}

      <h2 className="containers-page__subtitle">Your stacks</h2>

      {listLoading && stacks.length === 0 ? (
        <p className="containers-muted">Loading…</p>
      ) : stacks.length === 0 ? (
        <p className="containers-muted">
          No stacks yet. Create one or import a compose file.
        </p>
      ) : (
        <div className="containers-table-wrap">
          <table className="containers-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Network</th>
                <th>Services</th>
                <th>Created</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {stacks.map((stack) => (
                <StackRow
                  key={stack.id}
                  stack={stack}
                  busy={busy}
                  pendingDelete={pendingDelete}
                  onDeploy={handleDeploy}
                  onDelete={handleDelete}
                  onEdit={(id) => navigate(`/stacks/${id}`)}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="dashboard-page__actions">
        <button
          type="button"
          className="btn btn--ghost"
          onClick={() => {
            setBanner(null)
            void loadStacks()
          }}
          disabled={listLoading}
        >
          Refresh
        </button>
      </div>

      <BuildConfigModal
        open={buildConfigOpen}
        initial={buildConfigInitial}
        onCancel={closeBuildConfigModal}
        onConfirm={(override) => {
          void onBuildConfigConfirm(override)
        }}
      />
    </section>
  )
}
