import type { UserPublic } from '../api/client'
import { getUserInitials } from '../utils/userDisplay'

type UserAvatarProps = {
  user: Pick<UserPublic, 'display_name' | 'email' | 'avatar_url'>
  className?: string
  size?: number
}

export default function UserAvatar({
  user,
  className = '',
  size = 32,
}: UserAvatarProps) {
  const initials = getUserInitials(user)
  const classes = `user-avatar${className ? ` ${className}` : ''}`

  if (user.avatar_url) {
    return (
      <img
        className={classes}
        src={user.avatar_url}
        alt=""
        width={size}
        height={size}
      />
    )
  }

  return (
    <span
      className={`${classes} user-avatar--initials`}
      aria-hidden="true"
      style={{ width: size, height: size }}
    >
      {initials}
    </span>
  )
}
