import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from 'react'
import {
  ReactFlow,
  Background,
  getBezierPath,
  BaseEdge,
  EdgeLabelRenderer,
  Handle,
  Position,
  applyNodeChanges,
  type Node,
  type NodeChange,
  type Edge,
  type OnConnect,
  type EdgeProps,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import type { StackServiceCreate } from '../../api/client'

type DepEdgeData = { onRemove: () => void }
type ServiceNodeData = { label: string; isHighlighted?: boolean; isSel?: boolean }

function DependencyEdge(props: EdgeProps<Edge<DepEdgeData>>) {
  const { id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, data, selected } = props
  const [edgePath, edgeLabelX, edgeLabelY] = getBezierPath({
    sourceX,
    sourceY,
    sourcePosition,
    targetX,
    targetY,
    targetPosition,
  })
  return (
    <>
      <BaseEdge id={id} path={edgePath} style={{ stroke: selected ? '#9945d9' : '#5a4b7a', strokeWidth: 2 }} />
      <EdgeLabelRenderer>
        <div
          style={{
            position: 'absolute',
            transform: `translate(-50%, -50%) translate(${edgeLabelX}px, ${edgeLabelY}px)`,
            pointerEvents: 'all',
          }}
        >
          <button
            type="button"
            className="stacks-visualizer__edge-remove"
            aria-label="Remove dependency"
            onClick={(e) => {
              e.stopPropagation()
              data?.onRemove()
            }}
          >
            ×
          </button>
        </div>
      </EdgeLabelRenderer>
    </>
  )
}

const edgeTypes = { dependency: DependencyEdge }

function ServiceNode({ data }: { data: ServiceNodeData }) {
  return (
    <>
      <Handle type="target" position={Position.Left} />
      <div
        className={[
          'service-node__content',
          data.isHighlighted ? 'service-node__content--highlight' : '',
          data.isSel ? 'service-node__content--selected' : '',
        ]
          .filter(Boolean)
          .join(' ')}
      >
        <span className="service-node__name">{data.label}</span>
      </div>
      <Handle type="source" position={Position.Right} />
    </>
  )
}

const nodeTypes = { service: ServiceNode }

function serviceNodeId(service: StackServiceCreate, index: number): string {
  return service.service_name || `node-${index}`
}

function fallbackLabel(service: StackServiceCreate, index: number): string {
  const ref = service.source_ref || ''
  if (!ref) return `service-${index + 1}`
  if (service.source_kind === 'git') {
    const stripped = ref.replace(/\.(git)$/, '')
    const parts = stripped.split('/')
    return parts[parts.length - 1] || ref
  }
  if (service.source_kind === 'dockerfile_template') return ref
  const imageParts = ref.split('/')
  return imageParts[imageParts.length - 1] || ref
}

function buildNodesFromServices(
  services: StackServiceCreate[],
  highlightedIndex: number | null | undefined,
  selectedIndex: number | null | undefined,
  clickable: boolean,
  previous: Node[],
): Node[] {
  const previousById = new Map(previous.map((node) => [node.id, node]))
  const baseStyle: CSSProperties = {
    padding: '10px 16px',
    borderRadius: '8px',
    background: '#312654',
    color: '#e9e4f2',
    fontSize: '0.8125rem',
    fontWeight: 500,
    minWidth: '160px',
    textAlign: 'center',
    display: 'flex',
    flexDirection: 'column',
    gap: '4px',
    transition: 'border-color 0.3s ease',
    cursor: clickable ? 'pointer' : 'default',
  }

  return services.map((service, index) => {
    const id = serviceNodeId(service, index)
    const existing = previousById.get(id)
    const isHighlighted = highlightedIndex === index
    const isSel = selectedIndex === index
    return {
      id,
      type: 'service' as const,
      position: existing?.position ?? { x: index * 220, y: 50 },
      data: {
        label: service.service_name || fallbackLabel(service, index),
        isHighlighted,
        isSel,
      },
      style: {
        ...baseStyle,
        border: isHighlighted
          ? '2px solid #f59e0b'
          : isSel
            ? '2px solid #9945d9'
            : '1px solid #5a4b7a',
      },
      // Preserve measurement so React Flow can clear visibility:hidden.
      measured: existing?.measured,
      width: existing?.width,
      height: existing?.height,
    }
  })
}

export default function StackVisualizer({
  services,
  highlightedIndex,
  selectedIndex,
  onNodeClick,
  onDependencyChange,
}: {
  services: StackServiceCreate[]
  highlightedIndex?: number | null
  selectedIndex?: number | null
  onNodeClick?: (index: number) => void
  onDependencyChange?: (serviceIndex: number, dependsOn: string[] | null) => void
}) {
  const onDependencyChangeRef = useRef(onDependencyChange)
  const onNodeClickRef = useRef(onNodeClick)

  useEffect(() => {
    onDependencyChangeRef.current = onDependencyChange
  }, [onDependencyChange])

  useEffect(() => {
    onNodeClickRef.current = onNodeClick
  }, [onNodeClick])

  const [prefersReducedMotion, setPrefersReducedMotion] = useState(() =>
    window.matchMedia('(prefers-reduced-motion: reduce)').matches,
  )

  useEffect(() => {
    const query = window.matchMedia('(prefers-reduced-motion: reduce)')
    const onChange = (event: MediaQueryListEvent) => setPrefersReducedMotion(event.matches)
    query.addEventListener('change', onChange)
    return () => query.removeEventListener('change', onChange)
  }, [])

  const [baseNodes, setBaseNodes] = useState<Node[]>(() =>
    buildNodesFromServices(services, null, null, !!onNodeClick, []),
  )

  useEffect(() => {
    setBaseNodes((previous) =>
      buildNodesFromServices(services, null, null, !!onNodeClickRef.current, previous),
    )
  }, [services])

  const nodes = useMemo<Node[]>(
    () => {
      const nodeIdAt = (index: number | null | undefined): string | null => {
        if (index == null) return null
        const service = services[index]
        return service ? serviceNodeId(service, index) : null
      }
      const highlightedId = nodeIdAt(highlightedIndex)
      const selectedId = nodeIdAt(selectedIndex)
      return baseNodes.map((node) => {
        const isHighlighted = node.id === highlightedId
        const isSel = node.id === selectedId
        return {
          ...node,
          data: { ...node.data, isHighlighted, isSel },
          style: {
            ...node.style,
            border: isHighlighted
              ? '2px solid #f59e0b'
              : isSel
                ? '2px solid #9945d9'
                : '1px solid #5a4b7a',
          },
        }
      })
    },
    [baseNodes, highlightedIndex, selectedIndex, services],
  )

  const edges = useMemo<Edge[]>(
    () =>
      services
        .map((service, index) => {
          const sourceId = serviceNodeId(service, index)
          return (service.depends_on || []).map((dep) => ({
            id: `${sourceId}->${dep}`,
            source: sourceId,
            target: dep,
            type: 'dependency',
            animated: !prefersReducedMotion,
            data: {
              onRemove: () => {
                const handler = onDependencyChangeRef.current
                if (!handler) return
                const current = service.depends_on || []
                const next = current.filter((name) => name !== dep)
                handler(index, next.length > 0 ? next : null)
              },
            },
          }))
        })
        .flat()
        .filter((edge) => edge.source && edge.target),
    [services, prefersReducedMotion],
  )

  const onNodesChange = useCallback((changes: NodeChange[]) => {
    setBaseNodes((current) => applyNodeChanges(changes, current))
  }, [])

  const onEdgesChange = useCallback(() => {}, [])

  const onConnect: OnConnect = useCallback(
    (connection) => {
      const handler = onDependencyChangeRef.current
      if (!handler || !connection.target) return
      const sourceIndex = services.findIndex(
        (service, index) => serviceNodeId(service, index) === connection.source,
      )
      if (sourceIndex === -1) return
      const current = services[sourceIndex].depends_on || []
      if (current.includes(connection.target)) return
      handler(sourceIndex, [...current, connection.target])
    },
    [services],
  )

  const onNodeClickHandler = useCallback(
    (_: unknown, node: Node) => {
      const handler = onNodeClickRef.current
      if (!handler) return
      const index = services.findIndex(
        (service, serviceIndex) => serviceNodeId(service, serviceIndex) === node.id,
      )
      if (index !== -1) {
        handler(index)
      }
    },
    [services],
  )

  return (
    <div className="stacks-visualizer">
      <div className="stacks-visualizer__flow">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          edgeTypes={edgeTypes}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          onNodeClick={onNodeClickHandler}
          fitView
          elementsSelectable={true}
          defaultEdgeOptions={{ type: 'dependency' }}
        >
          <Background />
        </ReactFlow>
      </div>
    </div>
  )
}
