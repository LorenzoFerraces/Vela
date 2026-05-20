import type { ImagesBanner } from './types'

type ImagesMessageBannerProps = {
  banner: ImagesBanner
}

export function ImagesMessageBanner({ banner }: ImagesMessageBannerProps) {
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
