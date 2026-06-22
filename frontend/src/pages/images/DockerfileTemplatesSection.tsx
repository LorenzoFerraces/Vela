import { useState } from 'react'
import type { DockerfileTemplate } from '../../api/client'

const DEFAULT_NEW_DOCKERFILE = `FROM alpine:3.20
WORKDIR /app
CMD ["sh"]
`

type DockerfileTemplatesSectionProps = {
  rows: DockerfileTemplate[]
  listLoading: boolean
  busy: boolean
  selectedId: string | null
  editName: string
  editContents: string
  onEditNameChange: (value: string) => void
  onEditContentsChange: (value: string) => void
  onSelect: (template: DockerfileTemplate) => void
  onClearSelection: () => void
  onCreate: (name: string, contents: string) => Promise<boolean>
  onSave: () => void
  onRemove: (templateId: string) => void
}

export function DockerfileTemplatesSection({
  rows,
  listLoading,
  busy,
  selectedId,
  editName,
  editContents,
  onEditNameChange,
  onEditContentsChange,
  onSelect,
  onClearSelection,
  onCreate,
  onSave,
  onRemove,
}: DockerfileTemplatesSectionProps) {
  const [newName, setNewName] = useState('')
  const [newContents, setNewContents] = useState(DEFAULT_NEW_DOCKERFILE)

  async function handleCreate(event: React.FormEvent) {
    event.preventDefault()
    const created = await onCreate(newName, newContents)
    if (created) {
      setNewName('')
      setNewContents(DEFAULT_NEW_DOCKERFILE)
    }
  }

  return (
    <section
      className="images-section"
      aria-labelledby="dockerfile-templates-heading"
    >
      <h2 id="dockerfile-templates-heading" className="containers-page__subtitle">
        Dockerfile templates
      </h2>
      <p className="containers-muted images-section__lead">
        Name and edit Dockerfile snippets stored in your account.
      </p>

      <form
        className="containers-form images-section__form"
        onSubmit={handleCreate}
      >
        <label className="containers-form__label" htmlFor="new-template-name">
          New template name
        </label>
        <input
          id="new-template-name"
          className="containers-form__input"
          type="text"
          placeholder="my-service"
          value={newName}
          onChange={(event) => setNewName(event.target.value)}
        />
        <label className="containers-form__label" htmlFor="new-template-contents">
          Contents
        </label>
        <textarea
          id="new-template-contents"
          className="containers-form__input images-editor"
          rows={8}
          value={newContents}
          onChange={(event) => setNewContents(event.target.value)}
          spellCheck={false}
        />
        <div className="containers-form__actions">
          <button type="submit" className="btn btn--primary" disabled={busy}>
            {busy ? 'Creating…' : 'Create template'}
          </button>
        </div>
      </form>

      {listLoading && rows.length === 0 ? (
        <p className="containers-muted">Loading…</p>
      ) : rows.length === 0 ? (
        <p className="containers-muted">No Dockerfile templates yet.</p>
      ) : (
        <div className="images-templates-layout">
          <ul className="images-template-list" role="list">
            {rows.map((row) => (
              <li key={row.id}>
                <button
                  type="button"
                  className={
                    selectedId === row.id
                      ? 'images-template-list__item images-template-list__item--active'
                      : 'images-template-list__item'
                  }
                  onClick={() => onSelect(row)}
                >
                  {row.name}
                </button>
              </li>
            ))}
          </ul>

          {selectedId ? (
            <div className="images-editor-panel">
              <label className="containers-form__label" htmlFor="edit-template-name">
                Name
              </label>
              <input
                id="edit-template-name"
                className="containers-form__input"
                type="text"
                value={editName}
                onChange={(event) => onEditNameChange(event.target.value)}
              />
              <label
                className="containers-form__label"
                htmlFor="edit-template-contents"
              >
                Contents
              </label>
              <textarea
                id="edit-template-contents"
                className="containers-form__input images-editor"
                rows={14}
                value={editContents}
                onChange={(event) => onEditContentsChange(event.target.value)}
                spellCheck={false}
              />
              <div className="containers-form__actions">
                <button
                  type="button"
                  className="btn btn--primary"
                  disabled={busy}
                  onClick={() => onSave()}
                >
                  {busy ? 'Saving…' : 'Save changes'}
                </button>
                <button
                  type="button"
                  className="btn btn--ghost"
                  disabled={busy}
                  onClick={onClearSelection}
                >
                  Close
                </button>
                <button
                  type="button"
                  className="btn btn--danger"
                  disabled={busy}
                  onClick={() => {
                    if (
                      window.confirm(
                        `Delete Dockerfile template ${editName}?`
                      )
                    ) {
                      void onRemove(selectedId)
                    }
                  }}
                >
                  Delete
                </button>
              </div>
            </div>
          ) : (
            <p className="containers-muted images-editor-panel images-editor-panel--empty">
              Select a template to edit.
            </p>
          )}
        </div>
      )}
    </section>
  )
}
