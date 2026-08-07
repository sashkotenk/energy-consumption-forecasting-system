import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  AlgorithmType,
  ExperimentStatus,
  JobStatus,
  JobType,
  SensitivityMode,
  WeatherMode,
  type ExperimentResponse,
  type JobResponse,
} from '../generated/api/models'
import { api } from '../shared/api/client'
import { ExperimentDetailsPage } from './ExperimentDetailsPage'
import { ExperimentsPage } from './ExperimentsPage'

function client() {
  return new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
}

function experiment(status: ExperimentStatus): ExperimentResponse {
  const now = new Date('2026-08-08T00:00:00Z')
  const finished = status === ExperimentStatus.Failed || status === ExperimentStatus.Cancelled || status === ExperimentStatus.Completed
  return {
    algorithms: [AlgorithmType.SeasonalNaive24, AlgorithmType.Ridge],
    createdAt: now,
    datasetVersionId: 'version-1',
    failureCode: status === ExperimentStatus.Failed ? 'training_failed' : null,
    failureDetail: status === ExperimentStatus.Failed ? 'training failed for test' : null,
    finishedAt: finished ? now : null,
    id: 'exp-1',
    jobId: 'job-1',
    name: 'Тестовий експеримент',
    resultManifest: null,
    sensitivityMode: SensitivityMode.Coverage90,
    startedAt: now,
    status,
    weatherMode: WeatherMode.W0,
  }
}

function job(status: JobStatus): JobResponse {
  const now = new Date('2026-08-08T00:00:00Z')
  return {
    attempt: 1,
    attempts: [],
    cancelRequestedAt: null,
    createdAt: now,
    errorCode: null,
    errorDetail: null,
    finishedAt: null,
    heartbeatAt: now,
    id: 'job-1',
    jobType: JobType.Experiment,
    maxAttempts: 3,
    progressPct: 0,
    result: null,
    startedAt: now,
    status,
    updatedAt: now,
  }
}

function renderDetails() {
  return render(
    <QueryClientProvider client={client()}>
      <MemoryRouter initialEntries={['/experiments/exp-1']}>
        <Routes><Route path="/experiments/:experimentId" element={<ExperimentDetailsPage />} /></Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

afterEach(() => vi.restoreAllMocks())

describe('experiment workflow states', () => {
  it('renders the experiment history empty state', async () => {
    vi.spyOn(api.experiments, 'listExperiments').mockResolvedValue({ items: [], page: 1, pageSize: 50, total: 0 })
    render(<QueryClientProvider client={client()}><MemoryRouter><ExperimentsPage /></MemoryRouter></QueryClientProvider>)
    expect(await screen.findByRole('heading', { name: 'Експериментів ще немає' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Створити експеримент' })).toHaveAttribute('href', '/experiments/new')
  })

  it('shows failure details and retries the persisted job', async () => {
    vi.spyOn(api.experiments, 'getExperiment').mockResolvedValue(experiment(ExperimentStatus.Failed))
    vi.spyOn(api.jobs, 'getJob').mockResolvedValue(job(JobStatus.Queued))
    const retry = vi.spyOn(api.jobs, 'retryJob').mockResolvedValue(job(JobStatus.Queued))
    renderDetails()
    expect(await screen.findByRole('alert')).toHaveTextContent('training failed for test')
    fireEvent.click(screen.getByRole('button', { name: 'Повторити запуск' }))
    await waitFor(() => expect(retry).toHaveBeenCalledWith({ jobId: 'job-1' }))
  })

  it('renders cancelled as a terminal state without active cancellation controls', async () => {
    vi.spyOn(api.experiments, 'getExperiment').mockResolvedValue(experiment(ExperimentStatus.Cancelled))
    renderDetails()
    expect(await screen.findByRole('heading', { name: 'Експеримент скасовано' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Скасувати експеримент' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Запустити повторно' })).toBeInTheDocument()
  })
})
