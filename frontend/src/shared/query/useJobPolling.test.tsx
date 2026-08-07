import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { JobStatus, type JobResponse } from '../../generated/api/models'
import { api } from '../api/client'
import { useJobPolling } from './useJobPolling'

function Probe() {
  const query = useJobPolling('job-1')
  return <output>{query.data?.status ?? 'loading'}</output>
}

describe('useJobPolling', () => {
  it('stops polling after a terminal result', async () => {
    const now = new Date()
    const getJob = vi.spyOn(api.jobs, 'getJob').mockResolvedValue({
      attempt: 1,
      attempts: [],
      cancelRequestedAt: null,
      createdAt: now,
      errorCode: 'training_failed',
      errorDetail: 'test failure',
      finishedAt: now,
      heartbeatAt: now,
      id: 'job-1',
      jobType: 'experiment',
      maxAttempts: 3,
      progressPct: 100,
      result: null,
      startedAt: now,
      status: JobStatus.Failed,
      updatedAt: now,
    } as JobResponse)
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={client}><Probe /></QueryClientProvider>)
    expect(await screen.findByText('failed')).toBeInTheDocument()
    await new Promise((resolve) => window.setTimeout(resolve, 1650))
    expect(getJob).toHaveBeenCalledTimes(1)
  })
})
