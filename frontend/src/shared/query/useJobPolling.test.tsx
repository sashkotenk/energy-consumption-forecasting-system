import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { JobStatus, JobType, type JobResponse } from '../../generated/api/models'
import { api } from '../api/client'
import { nextJobPollDelay, useJobPolling } from './useJobPolling'

function response(status: JobStatus): JobResponse {
  const now = new Date()
  return {
    attempt: 1,
    attempts: [],
    cancelRequestedAt: null,
    createdAt: now,
    errorCode: status === JobStatus.Failed ? 'training_failed' : null,
    errorDetail: status === JobStatus.Failed ? 'test failure' : null,
    finishedAt: status === JobStatus.Failed ? now : null,
    heartbeatAt: now,
    id: 'job-1',
    jobType: JobType.Experiment,
    maxAttempts: 3,
    progressPct: status === JobStatus.Failed ? 100 : 25,
    result: null,
    startedAt: now,
    status,
    updatedAt: now,
  }
}

function Probe() {
  const query = useJobPolling('job-1')
  return <output>{query.data?.status ?? 'loading'}</output>
}

describe('useJobPolling', () => {
  it('caps progressive polling backoff', () => {
    expect(nextJobPollDelay(0)).toBe(1000)
    expect(nextJobPollDelay(1)).toBe(2000)
    expect(nextJobPollDelay(2)).toBe(4000)
    expect(nextJobPollDelay(3)).toBe(5000)
    expect(nextJobPollDelay(20)).toBe(5000)
  })

  it('stops polling after a terminal result', async () => {
    const getJob = vi.spyOn(api.jobs, 'getJob').mockResolvedValue(response(JobStatus.Failed))
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={client}><Probe /></QueryClientProvider>)
    expect(await screen.findByText('failed')).toBeInTheDocument()
    await new Promise((resolve) => window.setTimeout(resolve, 1650))
    expect(getJob).toHaveBeenCalledTimes(1)
  })

  it('does not keep polling after the component unmounts', async () => {
    const getJob = vi.spyOn(api.jobs, 'getJob').mockResolvedValue(response(JobStatus.Running))
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const view = render(<QueryClientProvider client={client}><Probe /></QueryClientProvider>)
    expect(await screen.findByText('running')).toBeInTheDocument()
    const callsBeforeUnmount = getJob.mock.calls.length
    expect(callsBeforeUnmount).toBeGreaterThan(0)
    view.unmount()
    await new Promise((resolve) => window.setTimeout(resolve, 2200))
    expect(getJob).toHaveBeenCalledTimes(callsBeforeUnmount)
  })
})
