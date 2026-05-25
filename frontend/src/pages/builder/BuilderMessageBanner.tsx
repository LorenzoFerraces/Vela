import type { BuilderBanner } from './types'

type BuilderMessageBannerProps = {
  banner: BuilderBanner
}

/**
 * Renders an alert banner for a provided BuilderBanner.
 *
 * @param banner - The banner object to display; if falsy, the component renders nothing.
 * @returns The banner element containing `banner.text` when `banner` is provided, otherwise `null`.
 */
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
