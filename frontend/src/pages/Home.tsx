import { useEffect, useState } from 'react'
import { ApiError, getHealth } from '../api/client'

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
      } catch (e) {
        if (!cancelled) {
          setApiStatus('error')
          setApiDetail(
            e instanceof ApiError ? `${e.status}: ${e.message}` : String(e)
          )
        }
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  return (
    <section className="hero">
      <p className="hero__eyebrow">Plataforma de despliegue</p>
      <h1 className="hero__title">Hola, esto es Vela</h1>
      <p className="hero__subtitle">
        Orquesta, construye y gestiona contenedores desde un solo lugar.
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
            API no disponible ({apiDetail})
          </>
        )}
      </div>
    </section>
  )
}
