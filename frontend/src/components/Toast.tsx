import { useEffect } from 'react'

type ToastProps = {
  message: string | null
  tone?: 'ok' | 'err'
  onDismiss: () => void
  autoDismissMs?: number
}

export function Toast({
  message,
  tone = 'ok',
  onDismiss,
  autoDismissMs = 3500,
}: ToastProps) {
  useEffect(() => {
    if (!message) {
      return
    }
    const timer = window.setTimeout(onDismiss, autoDismissMs)
    return () => window.clearTimeout(timer)
  }, [message, onDismiss, autoDismissMs])

  if (!message) {
    return null
  }

  return (
    <div
      className={`toast toast--${tone}`}
      role="status"
      aria-live="polite"
    >
      <p className="toast__text">{message}</p>
      <button
        type="button"
        className="toast__dismiss"
        aria-label="Dismiss notification"
        onClick={onDismiss}
      >
        ×
      </button>
    </div>
  )
}
