import type { ExportArtifactResponse } from '../../generated/api/models'
import { api } from './client'

export async function downloadControlledArtifact(artifact: ExportArtifactResponse) {
  const blob = await api.exports.downloadExportArtifact({ artifactId: artifact.id })
  const url = URL.createObjectURL(blob)
  try {
    const link = document.createElement('a')
    link.href = url
    link.download = artifact.filename
    link.rel = 'noopener'
    document.body.append(link)
    link.click()
    link.remove()
  } finally {
    URL.revokeObjectURL(url)
  }
}
