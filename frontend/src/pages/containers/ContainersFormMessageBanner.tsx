import { useState } from 'react'
import type { FormMessage } from './types'

type CopyHint = 'idle' | 'copied' | 'failed'

type ContainersFormMessageBannerProps = {
  message: FormMessage
}

export function ContainersFormMessageBanner({
  message,
}: ContainersFormMessageBannerProps) {
  const [copyHint, setCopyHint] = useState<CopyHint>('idle')

  return (
    <div
      className={
        message.type === 'ok'
          ? 'containers-banner containers-banner--ok'
          : 'containers-banner containers-banner--err'
      }
      role="alert"
    >
      <p className="containers-banner__text">{message.text}</p>
      {message.type === 'ok' && message.publicUrl ? (
        <div className="containers-public-url">
          <a
            className="containers-public-url__link"
            href={message.publicUrl}
            target="_blank"
            rel="noreferrer"
          >
            {message.publicUrl}
          </a>
          <button
            type="button"
            className="btn btn--ghost btn--sm"
            onClick={() => {
              const url = message.publicUrl
              if (!url) return
              void navigator.clipboard.writeText(url).then(
                () => {
                  setCopyHint('copied')
                  window.setTimeout(() => {
                    setCopyHint('idle')
                  }, 2000)
                },
                () => {
                  setCopyHint('failed')
                  window.setTimeout(() => {
                    setCopyHint('idle')
                  }, 2500)
                },
              )
            }}
          >
            {copyHint === 'copied'
              ? 'Copied'
              : copyHint === 'failed'
                ? 'Copy failed'
                : 'Copy URL'}
          </button>
        </div>
      ) : null}
    </div>
  )
}
