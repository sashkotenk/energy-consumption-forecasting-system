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

export function useJobPolling(jobId?: string | null, enabled = true) {
  return useQuery<JobResponse>({
    queryKey: ['job', jobId],
    queryFn: () => api.jobs.getJob({ jobId: jobId! }),
    enabled: Boolean(jobId) && enabled,
    refetchInterval: (query) => (isTerminalJob(query.state.data?.status) ? false : 1500),
    refetchIntervalInBackground: false,
    retry: 2,
  })
}
