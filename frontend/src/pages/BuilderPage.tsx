import { useCallback, useState } from 'react'
import { BuilderMessageBanner } from './builder/BuilderMessageBanner'
import { DockerfileTemplatesSection } from './builder/DockerfileTemplatesSection'
import type { BuilderBanner } from './builder/types'
import { useDockerfileTemplates } from './builder/useDockerfileTemplates'

export default function BuilderPage() {
  const [banner, setBanner] = useState<BuilderBanner>(null)

  const reportBanner = useCallback((next: BuilderBanner) => {
    setBanner(next)
  }, [])

  const dockerfiles = useDockerfileTemplates(reportBanner)

  return (
    <section className="builder-page">
      <h1 className="containers-page__title">Builder</h1>
      <p className="containers-page__lead">
        Manage Dockerfile templates for your account. Pick them when deploying a
        container from the Containers page.
      </p>

      <BuilderMessageBanner banner={banner} />

      <DockerfileTemplatesSection
        rows={dockerfiles.rows}
        listLoading={dockerfiles.listLoading}
        busy={dockerfiles.busy}
        selectedId={dockerfiles.selectedId}
        editName={dockerfiles.editName}
        editContents={dockerfiles.editContents}
        onEditNameChange={dockerfiles.setEditName}
        onEditContentsChange={dockerfiles.setEditContents}
        onSelect={dockerfiles.selectTemplate}
        onClearSelection={dockerfiles.clearSelection}
        onCreate={dockerfiles.createTemplate}
        onSave={() => void dockerfiles.saveSelected()}
        onRemove={(templateId) => void dockerfiles.removeTemplate(templateId)}
      />
    </section>
  )
}
