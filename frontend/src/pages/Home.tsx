import { useEffect, useState } from 'react'
import { formatApiError, getHealth } from '../api/client'

export default function Home() {
  const [apiStatus, setApiStatus] = useState<
    'idle' | 'ok' | 'error'
  >('idle')
  const [apiDetail, setApiDetail] = useState<string>('')

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const h = await getHealth()
        if (!cancelled) {
          setApiStatus('ok')
          setApiDetail(h.status)
        }
      } catch (error) {
        if (!cancelled) {
          setApiStatus('error')
          setApiDetail(formatApiError(error))
        }
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  return (
    <section className="hero">
      <p className="hero__eyebrow">Deployment platform</p>
      <h1 className="hero__title">Hello, this is Vela</h1>
      <p className="hero__subtitle">
        Orchestrate, build and manage containers from one place.
      </p>
      <div className="hero__status" role="status" aria-live="polite">
        {apiStatus === 'idle' && (
          <span className="hero__status-dot hero__status-dot--pending" />
        )}
        {apiStatus === 'ok' && (
          <>
            <span className="hero__status-dot hero__status-dot--ok" />
            API: {apiDetail}
          </>
        )}
        {apiStatus === 'error' && (
          <>
            <span className="hero__status-dot hero__status-dot--err" />
            {apiDetail}
          </>
        )}
      </div>
    </section>
  )
}
