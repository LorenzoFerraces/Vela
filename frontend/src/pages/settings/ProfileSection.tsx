import { useEffect, useRef, useState, type ChangeEvent, type FormEvent } from 'react'
import type { UserPublic } from '../../api/client'
import { TrashIcon} from '@phosphor-icons/react/Trash'
import {
  deleteAvatar,
  formatApiError,
  updateProfile,
  uploadAvatar,
} from '../../api/client'
import UserAvatar from '../../components/UserAvatar'

type ProfileBanner = { tone: 'ok' | 'err'; text: string } | null

function formatJoinedDate(iso: string | null): string {
  if (!iso) return '—'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return '—'
  return date.toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  })
}

type ProfileSectionProps = {
  user: UserPublic
  onProfileUpdated: () => Promise<void>
}

export default function ProfileSection({
  user,
  onProfileUpdated,
}: ProfileSectionProps) {
  const [displayName, setDisplayName] = useState(user.display_name ?? '')
  const [pronouns, setPronouns] = useState(user.pronouns ?? '')
  const [profileBusy, setProfileBusy] = useState(false)
  const [avatarBusy, setAvatarBusy] = useState(false)
  const [banner, setBanner] = useState<ProfileBanner>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    setDisplayName(user.display_name ?? '')
    setPronouns(user.pronouns ?? '')
  }, [user.display_name, user.pronouns])

  async function handleSaveProfile(event: FormEvent) {
    event.preventDefault()
    setProfileBusy(true)
    setBanner(null)
    try {
      await updateProfile({
        display_name: displayName.trim() || null,
        pronouns: pronouns.trim() || null,
      })
      await onProfileUpdated()
      setBanner({ tone: 'ok', text: 'Profile saved.' })
    } catch (error) {
      setBanner({ tone: 'err', text: formatApiError(error) })
    } finally {
      setProfileBusy(false)
    }
  }

  async function handleAvatarSelected(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file) return

    setAvatarBusy(true)
    setBanner(null)
    try {
      await uploadAvatar(file)
      await onProfileUpdated()
      setBanner({ tone: 'ok', text: 'Photo updated.' })
    } catch (error) {
      setBanner({ tone: 'err', text: formatApiError(error) })
    } finally {
      setAvatarBusy(false)
    }
  }

  async function handleRemoveAvatar() {
    if (!user.avatar_url) return
    if (!window.confirm('Remove your profile photo?')) return
    setAvatarBusy(true)
    setBanner(null)
    try {
      await deleteAvatar()
      await onProfileUpdated()
      setBanner({ tone: 'ok', text: 'Photo removed.' })
    } catch (error) {
      setBanner({ tone: 'err', text: formatApiError(error) })
    } finally {
      setAvatarBusy(false)
    }
  }

  const avatarDisabled = avatarBusy || profileBusy

  return (
    <>
      <h2 className="settings-page__section-title">Profile</h2>
      {banner ? (
        <p
          className={
            banner.tone === 'ok'
              ? 'settings-banner settings-banner--ok'
              : 'settings-banner settings-banner--err'
          }
          role={banner.tone === 'err' ? 'alert' : undefined}
        >
          {banner.text}
        </p>
      ) : null}
      <div className="settings-card">
        <div className="settings-card__body">
          <div className="settings-profile__header">
            <UserAvatar user={user} className="settings-github__avatar" size={44} />
            <div className="settings-profile__photo-actions">
              <input
                ref={fileInputRef}
                type="file"
                accept="image/jpeg,image/png,image/webp"
                className="settings-profile__file-input"
                aria-label="Upload profile photo"
                onChange={(event) => {
                  void handleAvatarSelected(event)
                }}
              />
              <button
                type="button"
                className="btn btn--ghost btn--sm"
                disabled={avatarDisabled}
                onClick={() => fileInputRef.current?.click()}
              >
                {avatarBusy ? 'Uploading…' : 'Upload photo'}
              </button>
              {user.avatar_url ? (
                <button
                type="button"
                className="btn btn--sm btn--danger settings-profile__remove-photo"
                disabled={avatarDisabled}
                aria-label="Remove photo"
                title="Remove photo"
                onClick={() => {
                  void handleRemoveAvatar()
                }}
              >
                <TrashIcon size={18} weight="regular" aria-hidden />
              </button>
              ) : null}
            </div>
          </div>

          <form className="settings-profile__form" onSubmit={handleSaveProfile}>
            <label className="auth-form__label" htmlFor="profile-display-name">
              Display name
            </label>
            <input
              id="profile-display-name"
              className="auth-form__input"
              value={displayName}
              maxLength={120}
              onChange={(event) => setDisplayName(event.target.value)}
            />

            <label className="auth-form__label" htmlFor="profile-pronouns">
              Pronouns
            </label>
            <input
              id="profile-pronouns"
              className="auth-form__input"
              value={pronouns}
              maxLength={40}
              placeholder="e.g. they/them"
              onChange={(event) => setPronouns(event.target.value)}
            />

            <dl className="settings-card__list settings-profile__meta">
              <div className="settings-card__row">
                <dt>Email</dt>
                <dd>{user.email}</dd>
              </div>
              <div className="settings-card__row">
                <dt>Member since</dt>
                <dd>{formatJoinedDate(user.created_at)}</dd>
              </div>
            </dl>

            <div className="settings-card__actions">
              <button
                type="submit"
                className="btn btn--primary"
                disabled={profileBusy || avatarBusy}
              >
                {profileBusy ? 'Saving…' : 'Save profile'}
              </button>
            </div>
          </form>
        </div>
      </div>
    </>
  )
}
