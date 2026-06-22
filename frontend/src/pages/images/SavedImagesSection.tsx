import { useState } from 'react'
import type { SavedImage } from '../../api/client'

type SavedImagesSectionProps = {
  rows: SavedImage[]
  listLoading: boolean
  busy: boolean
  onAdd: (ref: string) => Promise<boolean>
  onRemove: (imageId: string) => void
}

export function SavedImagesSection({
  rows,
  listLoading,
  busy,
  onAdd,
  onRemove,
}: SavedImagesSectionProps) {
  const [newRef, setNewRef] = useState('')

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    const saved = await onAdd(newRef)
    if (saved) {
      setNewRef('')
    }
  }

  return (
    <section className="images-section" aria-labelledby="saved-images-heading">
      <h2 id="saved-images-heading" className="containers-page__subtitle">
        Saved image references
      </h2>
      <p className="containers-muted images-section__lead">
        Store Docker image refs (e.g. <code>nginx:alpine</code>) for quick reuse.
      </p>

      <form className="containers-form images-section__form" onSubmit={handleSubmit}>
        <label className="containers-form__label" htmlFor="saved-image-ref">
          Image reference
        </label>
        <input
          id="saved-image-ref"
          className="containers-form__input"
          type="text"
          placeholder="nginx:alpine"
          value={newRef}
          onChange={(event) => setNewRef(event.target.value)}
          autoComplete="off"
        />
        <div className="containers-form__actions">
          <button type="submit" className="btn btn--primary" disabled={busy}>
            {busy ? 'Saving…' : 'Save reference'}
          </button>
        </div>
      </form>

      {listLoading && rows.length === 0 ? (
        <p className="containers-muted">Loading…</p>
      ) : rows.length === 0 ? (
        <p className="containers-muted">No saved image references yet.</p>
      ) : (
        <div className="containers-table-wrap">
          <table className="containers-table">
            <thead>
              <tr>
                <th>Reference</th>
                <th>Saved</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id}>
                  <td className="containers-table__mono">{row.ref}</td>
                  <td className="containers-muted">
                    {new Date(row.created_at).toLocaleString()}
                  </td>
                  <td className="containers-table__actions">
                    <button
                      type="button"
                      className="btn btn--sm btn--danger"
                      disabled={busy}
                      onClick={() => {
                        if (
                          window.confirm(
                            `Remove saved reference ${row.ref}?`
                          )
                        ) {
                          void onRemove(row.id)
                        }
                      }}
                    >
                      Remove
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
