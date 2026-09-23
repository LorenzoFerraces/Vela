import { useCallback, useState } from 'react'
import { ImagesMessageBanner } from './images/ImagesMessageBanner'
import type { ImagesBanner } from './images/types'
import { DockerfileTemplatesSection } from '../components/DockerfileTemplatesSection'
import { useDockerfileTemplates } from '../components/useDockerfileTemplates'

export default function ImagesPage() {
  const [banner, setBanner] = useState<ImagesBanner>(null)

  const reportBanner = useCallback((next: ImagesBanner) => {
    setBanner(next)
  }, [])

  const dockerfiles = useDockerfileTemplates(reportBanner)

  return (
    <section className="images-page">
      <h1 className="containers-page__title">Images</h1>
      <p className="containers-page__lead">
        Manage Dockerfile templates for your account.
      </p>

      <ImagesMessageBanner banner={banner} />

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
        leadText="Name and edit Dockerfile snippets stored in your account."
      />
    </section>
  )
}
