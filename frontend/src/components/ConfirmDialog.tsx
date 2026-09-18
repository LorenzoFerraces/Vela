import { useEffect, useId, useRef } from 'react'
import type { ReactNode } from 'react'

type ConfirmDialogProps = {
  open: boolean
  title: string
  message: ReactNode
  confirmLabel?: string
  cancelLabel?: string
  busy?: boolean
  onConfirm: () => void
  onClose: () => void
}

export default function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel = 'Confirm',
  cancelLabel = 'Cancel',
  busy = false,
  onConfirm,
  onClose,
}: ConfirmDialogProps) {
  const titleId = useId()
  const cancelButtonRef = useRef<HTMLButtonElement>(null)
  const confirmButtonRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    if (!open) {
      return
    }
    const previouslyFocused = document.activeElement as HTMLElement | null
    cancelButtonRef.current?.focus()
    return () => {
      previouslyFocused?.focus()
    }
  }, [open])

  useEffect(() => {
    if (!open) {
      return
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        if (busy) {
          return
        }
        event.preventDefault()
        onClose()
        return
      }
      if (event.key !== 'Tab' || busy) {
        return
      }
      const cancelButton = cancelButtonRef.current
      const confirmButton = confirmButtonRef.current
      if (!cancelButton || !confirmButton) {
        return
      }
      if (event.shiftKey && document.activeElement === cancelButton) {
        event.preventDefault()
        confirmButton.focus()
      } else if (!event.shiftKey && document.activeElement === confirmButton) {
        event.preventDefault()
        cancelButton.focus()
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => {
      window.removeEventListener('keydown', onKeyDown)
    }
  }, [open, busy, onClose])

  if (!open) {
    return null
  }

  return (
    <div
      className="stacks-modal-backdrop"
      role="presentation"
      onClick={busy ? undefined : onClose}
    >
      <div
        className="stacks-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        onClick={(event) => event.stopPropagation()}
      >
        <header className="stacks-modal__header">
          <h2 id={titleId} className="stacks-modal__title">
            {title}
          </h2>
          <p className="stacks-modal__lead">{message}</p>
        </header>

        <footer className="stacks-modal__footer">
          <button
            type="button"
            ref={cancelButtonRef}
            className="btn btn--ghost"
            onClick={onClose}
            disabled={busy}
          >
            {cancelLabel}
          </button>
          <button
            type="button"
            ref={confirmButtonRef}
            className="btn btn--danger"
            onClick={onConfirm}
            disabled={busy}
          >
            {confirmLabel}
          </button>
        </footer>
      </div>
    </div>
  )
}
