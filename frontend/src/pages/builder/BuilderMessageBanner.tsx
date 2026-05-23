import type { BuilderBanner } from './types'

type BuilderMessageBannerProps = {
  banner: BuilderBanner
}

export function BuilderMessageBanner({ banner }: BuilderMessageBannerProps) {
  if (!banner) {
    return null
  }
  return (
    <div
      className={
        banner.tone === 'ok'
          ? 'containers-banner containers-banner--ok'
          : 'containers-banner containers-banner--err'
      }
      role="alert"
    >
      <p className="containers-banner__text">{banner.text}</p>
    </div>
  )
}
