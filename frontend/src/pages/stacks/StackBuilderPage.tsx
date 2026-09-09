import { useCallback, useEffect, useState, memo } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  createStack,
  formatApiError,
  getStack,
  updateStack,
  type StackServiceCreate,
} from '../../api/client'
import ConfirmDialog from '../../components/ConfirmDialog'
import { ServiceEditForm, type ServiceFieldErrors } from './ServiceEditForm'
import StackVisualizer from './StackVisualizer'

type Banner = { tone: 'ok' | 'err'; text: string } | null

type StackServiceRow = StackServiceCreate & { uid: string }

function graphServicesEqual(
  prev: StackServiceCreate[],
  next: StackServiceCreate[],
): boolean {
  if (prev.length !== next.length) return false
  for (let i = 0; i < prev.length; i += 1) {
    const a = prev[i]
    const b = next[i]
    if (a.service_name !== b.service_name) return false
    if ((a.depends_on || []).join('\u0000') !== (b.depends_on || []).join('\u0000')) {
      return false
    }
    if (a.source_ref !== b.source_ref || a.source_kind !== b.source_kind) return false
  }
  return true
}

// ponytail: structural compare — env/command/ports edits must not re-render ReactFlow
const StackVisualizerMemo = memo(
  StackVisualizer,
  (prev, next) =>
    graphServicesEqual(prev.services, next.services) &&
    prev.highlightedIndex === next.highlightedIndex &&
    prev.selectedIndex === next.selectedIndex &&
    prev.onNodeClick === next.onNodeClick &&
    prev.onDependencyChange === next.onDependencyChange,
)

export default function StackBuilderPage() {
  const { id: editId } = useParams<{ id?: string }>()
  const navigate = useNavigate()
  const [services, setServices] = useState<StackServiceRow[]>([])
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null)
  const [highlightIndex, setHighlightIndex] = useState<number | null>(null)
  const [listLoading, setListLoading] = useState(!!editId)
  const [banner, setBanner] = useState<Banner>(null)
  const [stackName, setStackName] = useState('')
  const [saving, setSaving] = useState(false)
  const [serviceErrors, setServiceErrors] = useState<(ServiceFieldErrors | null)[]>([])
  const [removalPendingIndex, setRemovalPendingIndex] = useState<number | null>(null)
  useEffect(() => {
    if (!editId) return
    let cancelled = false
    ;(async () => {
      try {
        const stack = await getStack(editId)
        if (cancelled) return
        setStackName(stack.name)
        setServices(
          stack.services.map((s) => ({
            service_name: s.service_name,
            source_kind: s.source_kind,
            source_ref: s.source_ref,
            git_branch: s.git_branch,
            container_port: s.container_port,
            env_vars: s.env_vars,
            command: s.command,
            public_route: s.public_route,
            depends_on: s.depends_on,
            volumes: s.volumes,
            scaling_policy: s.scaling_policy,
            build_override: s.build_override ?? null,
            uid: crypto.randomUUID(),
          }))
        )
      } catch (err) {
        if (!cancelled) setBanner({ tone: 'err', text: formatApiError(err) })
      } finally {
        if (!cancelled) setListLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [editId])

  const updateService = useCallback(
    (index: number, field: keyof StackServiceCreate, value: unknown) => {
      setServices((prev) =>
        prev.map((s, i) => (i === index ? { ...s, [field]: value } : s))
      )
      if (field === 'service_name' || field === 'source_ref') {
        setServiceErrors((prev) => {
          const entry = prev[index]
          const hasError =
            entry && (field === 'service_name' ? entry.name : entry.source)
          if (!hasError) {
            return prev
          }
          return prev.map((item, i) => {
            if (i !== index || !item) {
              return item
            }
            if (field === 'service_name') {
              return { ...item, name: null }
            }
            return { ...item, source: null }
          })
        })
      }
    },
    []
  )

  const patchService = useCallback(
    (index: number, patch: Partial<StackServiceCreate>) => {
      setServices((prev) =>
        prev.map((s, i) => (i === index ? { ...s, ...patch } : s))
      )
      if (patch.source_ref !== undefined) {
        setServiceErrors((prev) => {
          const entry = prev[index]
          if (!entry || !entry.source) {
            return prev
          }
          return prev.map((item, i) => {
            if (i !== index || !item) {
              return item
            }
            return { ...item, source: null }
          })
        })
      }
    },
    []
  )

  const handleVisualizerNodeClick = useCallback(
    (index: number) => setSelectedIndex((prev) => (prev === index ? null : index)),
    []
  )

  const handleDependencyChange = useCallback(
    (serviceIndex: number, dependsOn: string[] | null) =>
      updateService(serviceIndex, 'depends_on', dependsOn),
    [updateService]
  )

  const removeService = useCallback(
    (index: number) => {
      setServices((prev) => prev.filter((_, i) => i !== index))
      setServiceErrors((prev) => prev.filter((_, i) => i !== index))
      setSelectedIndex((prev) => {
        if (prev === index) return null
        if (prev !== null && prev > index) return prev - 1
        return prev
      })
    },
    []
  )

  function addService() {
    const newService: StackServiceRow = {
      service_name: '',
      source_kind: 'image',
      source_ref: '',
      git_branch: null,
      container_port: 80,
      public_route: false,
      build_override: null,
      uid: crypto.randomUUID(),
    }
    const newIndex = services.length
    setServices((prev) => [...prev, newService])
    setSelectedIndex(newIndex)
    setHighlightIndex(newIndex)
    setTimeout(() => setHighlightIndex(null), 2000)
    setServiceErrors((prev) => [...prev, null])
  }

  async function handleSave() {
    if (services.length === 0) {
      setBanner({ tone: 'err', text: 'Stack must have at least one service.' })
      return
    }
    const errors = services.map(
      (service): ServiceFieldErrors => ({
        name: service.service_name.trim() ? null : 'Enter a service name.',
        source: service.source_ref.trim() ? null : 'Choose a deploy source.',
      }),
    )
    const firstInvalidIndex = errors.findIndex(
      (entry) => entry.name || entry.source,
    )
    if (firstInvalidIndex !== -1) {
      setServiceErrors(errors)
      setBanner({
        tone: 'err',
        text: 'Each service needs a name and deploy source.',
      })
      const firstInvalid = errors[firstInvalidIndex]
      if (firstInvalidIndex === selectedIndex) {
        const elementId = firstInvalid.name
          ? `svc-${firstInvalidIndex}-name`
          : 'deploy-source-input'
        document.getElementById(elementId)?.focus()
      } else {
        setSelectedIndex(firstInvalidIndex)
      }
      return
    }
    setServiceErrors(services.map(() => null))
    setSaving(true)
    const servicePayload = services.map((service): StackServiceCreate => ({
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
      build_override: service.build_override,
    }))
    try {
      if (editId) {
        await updateStack(editId, {
          name: stackName || 'untitled-stack',
          services: servicePayload,
        })
      } else {
        await createStack({
          name: stackName || 'untitled-stack',
          services: servicePayload,
        })
      }
      navigate('/stacks')
    } catch (err) {
      setBanner({ tone: 'err', text: formatApiError(err) })
    } finally {
      setSaving(false)
    }
  }

  const removalPending =
    removalPendingIndex !== null
      ? {
          index: removalPendingIndex,
          name:
            services[removalPendingIndex]?.service_name ||
            `service-${removalPendingIndex + 1}`,
        }
      : null

  const selectedService =
    selectedIndex !== null ? services[selectedIndex] : null

  return (
    <section className="stacks-builder-page">
      <h1 className="containers-page__title">
        {editId ? 'Edit Stack' : 'New Stack'}
      </h1>
      <p className="containers-page__lead">
        Define services and their dependencies, then deploy as a group.
      </p>

      <form className="containers-form" onSubmit={(e) => e.preventDefault()}>
        <label
          className="containers-form__label"
          htmlFor="stack-name-input"
        >
          Stack name
        </label>
        <input
          id="stack-name-input"
          className="containers-form__input"
          autoComplete="off"
          placeholder="my-stack"
          value={stackName}
          onChange={(e) => setStackName(e.target.value)}
        />
      </form>

      {banner ? (
        <div
          className={
            banner.tone === 'ok'
              ? 'containers-banner containers-banner--ok'
              : 'containers-banner containers-banner--err'
          }
          role={banner.tone === 'err' ? 'alert' : 'status'}
        >
          <p className="containers-banner__text">{banner.text}</p>
        </div>
      ) : null}

      {listLoading ? (
        <p className="containers-muted">Loading…</p>
      ) : (
        <div className="stacks-builder__split">
          <div className="stacks-builder__form-col">
            <h2 className="containers-page__subtitle">Services</h2>

            {services.length === 0 ? (
              <p className="containers-muted">
                No services yet. Add one to get started.
              </p>
            ) : (
              <>
                <ul className="stacks-builder__list" role="list">
                  {services.map((service, index) => {
                    if (selectedIndex === index) return null
                    return (
                      <li key={service.uid}>
                        <button
                          type="button"
                          className={[
                            'stacks-builder__list-item',
                            highlightIndex === index
                              ? 'stacks-builder__list-item--highlight'
                              : '',
                          ]
                            .filter(Boolean)
                            .join(' ')}
                          onClick={() =>
                            setSelectedIndex((prev) => (prev === index ? null : index))
                          }
                        >
                          {service.service_name || `service-${index + 1}`}
                        </button>
                      </li>
                    )
                  })}
                </ul>

                {selectedService !== null && (
                  <ServiceEditForm
                    key={selectedIndex}
                    service={selectedService}
                    index={selectedIndex!}
                    fieldErrors={serviceErrors[selectedIndex!] ?? null}
                    onUpdate={updateService}
                    onPatch={patchService}
                    onRemove={(index) => setRemovalPendingIndex(index)}
                    onClose={() => setSelectedIndex(null)}
                    siblingNames={services
                      .filter((_, i) => i !== selectedIndex)
                      .map((s) => s.service_name)
                      .filter((n): n is string => !!n && n.length > 0)}
                    onSelectSibling={(serviceName) => {
                      const nextIndex = services.findIndex(
                        (candidate) => candidate.service_name === serviceName,
                      )
                      if (nextIndex === -1) return
                      setSelectedIndex(nextIndex)
                      setHighlightIndex(nextIndex)
                      window.setTimeout(() => setHighlightIndex(null), 2000)
                    }}
                  />
                )}
              </>
            )}

            <div className="stacks-builder__actions">
              <button
                type="button"
                className="btn btn--ghost"
                onClick={addService}
              >
                + Add Service
              </button>
              <button
                type="button"
                className="btn btn--primary"
                onClick={handleSave}
                disabled={saving}
              >
                {saving ? 'Saving…' : 'Save Stack'}
              </button>
              <button
                type="button"
                className="btn btn--ghost"
                onClick={() => navigate('/stacks')}
              >
                Cancel
              </button>
            </div>
          </div>

          <div className="stacks-builder__graph-col">
            {services.length > 0 ? (
              <StackVisualizerMemo
                services={services}
                highlightedIndex={highlightIndex}
                selectedIndex={selectedIndex}
                onNodeClick={handleVisualizerNodeClick}
                onDependencyChange={handleDependencyChange}
              />
            ) : (
              <div className="stacks-visualizer">
                <div className="stacks-visualizer__flow containers-muted">
                  Add services to see the graph
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      <ConfirmDialog
        open={removalPending !== null}
        title="Remove service?"
        message={
          removalPending
            ? `“${removalPending.name}” and its env vars and volume mounts will be removed. Its uploaded folder stays in your storage and can be reused.`
            : ''
        }
        confirmLabel="Remove"
        onConfirm={() => {
          if (removalPending) {
            removeService(removalPending.index)
          }
          setRemovalPendingIndex(null)
        }}
        onClose={() => setRemovalPendingIndex(null)}
      />
    </section>
  )
}
