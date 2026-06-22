import { useCallback, useState } from 'react'
import { DockerfileTemplatesSection } from './images/DockerfileTemplatesSection'
import { ImagesMessageBanner } from './images/ImagesMessageBanner'
import { SavedImagesSection } from './images/SavedImagesSection'
import type { ImagesBanner } from './images/types'
import { useDockerfileTemplates } from './images/useDockerfileTemplates'
import { useSavedImages } from './images/useSavedImages'

export default function ImagesPage() {
  const [banner, setBanner] = useState<ImagesBanner>(null)

  const reportBanner = useCallback((next: ImagesBanner) => {
    setBanner(next)
  }, [])

  const savedImages = useSavedImages(reportBanner)
  const dockerfiles = useDockerfileTemplates(reportBanner)

  return (
    <section className="images-page">
      <h1 className="containers-page__title">Images</h1>
      <p className="containers-page__lead">
        Manage saved registry references and Dockerfile templates for your account.
      </p>

      <ImagesMessageBanner banner={banner} />

      <SavedImagesSection
        rows={savedImages.rows}
        listLoading={savedImages.listLoading}
        busy={savedImages.busy}
        onAdd={savedImages.addImage}
        onRemove={(imageId) => void savedImages.removeImage(imageId)}
      />

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
