import { afterEach, describe, expect, it, vi } from 'vitest'
import { ArtifactPurpose, type ExportArtifactResponse } from '../../generated/api/models'
import { api } from './client'
import { downloadControlledArtifact } from './download'

afterEach(() => vi.restoreAllMocks())

describe('controlled artifact download', () => {
  it('downloads bytes through the generated artifact endpoint instead of the response URL', async () => {
    const artifact: ExportArtifactResponse = {
      createdAt: new Date('2026-08-08T00:00:00Z'),
      downloadUrl: 'https://storage.invalid/private-key',
      filename: 'forecast.csv',
      id: 'artifact-1',
      mediaType: 'text/csv',
      purpose: ArtifactPurpose.ForecastExport,
      sha256: 'a'.repeat(64),
      sizeBytes: 4,
    }
    const download = vi.spyOn(api.exports, 'downloadExportArtifact').mockResolvedValue(new Blob(['test']))
    const createObjectURL = vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:test')
    const revokeObjectURL = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined)
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined)

    await downloadControlledArtifact(artifact)

    expect(download).toHaveBeenCalledWith({ artifactId: 'artifact-1' })
    expect(createObjectURL).toHaveBeenCalledTimes(1)
    expect(click).toHaveBeenCalledTimes(1)
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:test')
  })
})
