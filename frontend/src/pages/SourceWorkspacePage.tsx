import type { ReactNode } from 'react'
import { Skeleton } from '../components/Skeleton'
import './source-page.css'

type SourceWorkspacePageProps = {
  title: string
  children: ReactNode
  message: { tone: 'ok' | 'err'; text: string } | null
  loading: boolean
}

export default function SourceWorkspacePage({
  title,
  children,
  message,
  loading,
}: SourceWorkspacePageProps) {
  return (
    <section className="source-workspace-page">
      <h1 className="containers-page__title">{title}</h1>
      {message ? (
        <div
          className={
            message.tone === 'ok'
              ? 'containers-banner containers-banner--ok'
              : 'containers-banner containers-banner--err'
          }
          role={message.tone === 'ok' ? 'status' : 'alert'}
        >
          <p className="containers-banner__text">{message.text}</p>
        </div>
      ) : null}
      {loading ? (
        <div className="source-workspace-page__loading" role="status" aria-live="polite">
          <Skeleton className="skeleton--detail-title" />
          <Skeleton className="skeleton--team-row" />
          <Skeleton className="skeleton--team-row" />
        </div>
      ) : (
        children
      )}
    </section>
  )
}
