import { useCallback, useState } from 'react'
import { DockerfileTemplatesSection } from '../components/DockerfileTemplatesSection'
import {
  useDockerfileTemplates,
  type DockerfileTemplateBanner,
} from '../components/useDockerfileTemplates'
import SourceWorkspacePage from './SourceWorkspacePage'

export default function BuilderPage() {
  const [banner, setBanner] = useState<DockerfileTemplateBanner>(null)

  const reportBanner = useCallback((next: DockerfileTemplateBanner) => {
    setBanner(next)
  }, [])

  const dockerfiles = useDockerfileTemplates(reportBanner)

  return (
    <SourceWorkspacePage title="Builder" message={banner} loading={dockerfiles.listLoading}>
      <p className="containers-page__lead">
        Manage Dockerfile templates for your account. Pick them when deploying a
        container from the Containers page.
      </p>
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
        leadText="Create and edit Dockerfiles to use when deploying containers."
      />
    </SourceWorkspacePage>
  )
}
