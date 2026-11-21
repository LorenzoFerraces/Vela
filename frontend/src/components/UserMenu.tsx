import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  CaretDown,
  ClockCounterClockwise,
  GearSix,
  SignOut,
} from '@phosphor-icons/react'
import type { UserPublic } from '../api/client'
import { getUserDisplayLabel } from '../utils/userDisplay'
import UserAvatar from './UserAvatar'

type UserMenuProps = {
  user: UserPublic
  onLogout: () => void
}

export default function UserMenu({ user, onLogout }: UserMenuProps) {
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    if (!open) {
      return
    }
    function onMouseDown(event: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) {
        setOpen(false)
      }
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        event.preventDefault()
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', onMouseDown)
    window.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('mousedown', onMouseDown)
      window.removeEventListener('keydown', onKeyDown)
      triggerRef.current?.focus()
    }
  }, [open])

  function handleLogout() {
    setOpen(false)
    onLogout()
  }

  return (
    <div className="user-menu" ref={rootRef}>
      <button
        ref={triggerRef}
        type="button"
        className="user-menu__trigger"
        aria-haspopup="true"
        aria-expanded={open}
        title={user.email}
        onClick={() => setOpen((previous) => !previous)}
      >
        <UserAvatar user={user} className="user-menu__avatar" size={28} />
        <span className="user-menu__label">{getUserDisplayLabel(user)}</span>
        <CaretDown size={14} aria-hidden="true" />
      </button>
      {open && (
        <div className="user-menu__menu" aria-label="Account">
          <Link
            to="/settings"
            className="user-menu__item"
            onClick={() => setOpen(false)}
          >
            <GearSix size={16} aria-hidden="true" />
            Settings
          </Link>
          <Link
            to="/audit"
            className="user-menu__item"
            onClick={() => setOpen(false)}
          >
            <ClockCounterClockwise size={16} aria-hidden="true" />
            Audit Log
          </Link>
          <div className="user-menu__divider" role="separator" />
          <button
            type="button"
            className="user-menu__item user-menu__item--danger"
            onClick={handleLogout}
          >
            <SignOut size={16} aria-hidden="true" />
            Log out
          </button>
        </div>
      )}
    </div>
  )
}
