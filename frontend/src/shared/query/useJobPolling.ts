import { useQuery } from '@tanstack/react-query'
import { JobStatus, type JobResponse } from '../../generated/api/models'
import { api } from '../api/client'

const terminal = new Set<string>([
  JobStatus.Cancelled,
  JobStatus.Succeeded,
  JobStatus.Failed,
  JobStatus.Stale,
])

export function isTerminalJob(status?: string | null) {
  return status ? terminal.has(status) : false
}

export function nextJobPollDelay(updateCount: number) {
  return Math.min(5_000, 1_000 * 2 ** Math.min(updateCount, 3))
}

export function useJobPolling(jobId?: string | null, enabled = true) {
  return useQuery<JobResponse>({
    queryKey: ['job', jobId],
    queryFn: () => api.jobs.getJob({ jobId: jobId! }),
    enabled: Boolean(jobId) && enabled,
    refetchInterval: (query) => {
      if (isTerminalJob(query.state.data?.status)) return false
      return nextJobPollDelay(query.state.dataUpdateCount)
    },
    refetchIntervalInBackground: false,
    retry: 2,
  })
}
