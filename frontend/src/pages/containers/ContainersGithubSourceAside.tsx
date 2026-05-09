import { Link } from 'react-router-dom'
import type { GithubStatus } from '../../api/client'

type ContainersGithubSourceAsideProps = {
  authStatus: string
  userId: string | undefined
  githubStatus: GithubStatus | null
  repoPickerOpen: boolean
  onToggleRepoPicker: () => void
}

export function ContainersGithubSourceAside({
  authStatus,
  userId,
  githubStatus,
  repoPickerOpen,
  onToggleRepoPicker,
}: ContainersGithubSourceAsideProps) {
  if (authStatus !== 'authenticated' || !userId) {
    return null
  }
  if (githubStatus === null) {
    return (
      <span
        className="containers-form__github-aside"
        role="status"
        aria-live="polite"
      >
        Checking GitHub…
      </span>
    )
  }
  if (githubStatus.connected) {
    return (
      <button
        type="button"
        className="btn btn--ghost btn--sm"
        onClick={onToggleRepoPicker}
      >
        {repoPickerOpen ? 'Hide picker' : 'Pick from GitHub'}
      </button>
    )
  }
  return (
    <span className="containers-form__github-aside">
      <Link to="/settings">Connect GitHub</Link>
      {' · '}
      pick a repo
    </span>
  )
}
