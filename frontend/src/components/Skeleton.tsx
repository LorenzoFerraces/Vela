type SkeletonProps = {
  className?: string
}

export function Skeleton({ className = '' }: SkeletonProps) {
  const classes = className ? `skeleton ${className}` : 'skeleton'
  return <span className={classes} aria-hidden />
}

type TeamDetailSkeletonProps = {
  showInviteSection: boolean
}

export function TeamDetailSkeleton({ showInviteSection }: TeamDetailSkeletonProps) {
  return (
    <div aria-busy="true" aria-label="Loading team details">
      <section className="teams-page__section">
        <h3 className="teams-page__section-title">Members</h3>
        <ul className="teams-page__member-list">
          {[0, 1, 2].map((index) => (
            <li key={index} className="teams-page__member-row">
              <Skeleton className="skeleton--member-email" />
              <Skeleton className="skeleton--member-role" />
            </li>
          ))}
        </ul>
      </section>

      {showInviteSection ? (
        <section className="teams-page__section">
          <h3 className="teams-page__section-title">Invite member</h3>
          <div className="teams-page__invite-form">
            <Skeleton className="skeleton--invite-field" />
            <Skeleton className="skeleton--invite-role" />
            <Skeleton className="skeleton--invite-button" />
          </div>
        </section>
      ) : (
        <section className="teams-page__section">
          <Skeleton className="skeleton--hint-line" />
        </section>
      )}
    </div>
  )
}

export function TeamsPageSkeleton() {
  return (
    <div className="teams-page__layout" aria-busy="true" aria-label="Loading teams">
      <aside className="teams-page__sidebar">
        <h2 className="teams-page__sidebar-title">Your teams</h2>
        <ul className="teams-page__team-list">
          {[0, 1, 2].map((index) => (
            <li key={index}>
              <Skeleton className="skeleton--team-row" />
            </li>
          ))}
        </ul>
      </aside>

      <div className="teams-page__detail">
        <div className="teams-page__detail-header">
          <div>
            <Skeleton className="skeleton--detail-title" />
            <Skeleton className="skeleton--detail-description" />
          </div>
        </div>
        <TeamDetailSkeleton showInviteSection />
      </div>
    </div>
  )
}
