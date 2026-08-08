import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { MemoryRouter, Route, Routes } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  AlgorithmType,
  ExperimentStatus,
  SensitivityMode,
  WeatherMode,
  type ExperimentResponse,
} from '../generated/api/models'
import { api } from '../shared/api/client'
import { EChart } from '../shared/ui/EChart'
import { DataQualityPage } from './DataQualityPage'
import { ImportWizardPage } from './ImportWizardPage'
import { ModelComparisonPage } from './ModelComparisonPage'

const { chartInstance } = vi.hoisted(() => ({
  chartInstance: {
    setOption: vi.fn(),
    resize: vi.fn(),
    dispose: vi.fn(),
  },
}))

vi.mock('echarts', () => ({ init: vi.fn(() => chartInstance) }))

function queryClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
}

function renderRoute(path: string, routePath: string, element: ReactNode) {
  return render(
    <QueryClientProvider client={queryClient()}>
      <MemoryRouter initialEntries={[path]}>
        <Routes><Route path={routePath} element={element} /></Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

function completedExperiment(): ExperimentResponse {
  const now = new Date('2026-08-08T00:00:00Z')
  return {
    algorithms: [AlgorithmType.SeasonalNaive24, AlgorithmType.Ridge],
    createdAt: now,
    datasetVersionId: 'version-hourly',
    failureCode: null,
    failureDetail: null,
    finishedAt: now,
    id: 'exp-1',
    jobId: 'job-exp',
    name: 'Синтетичне порівняння',
    resultManifest: { schema: 'experiment-result/v1' },
    sensitivityMode: SensitivityMode.Coverage90,
    startedAt: now,
    status: ExperimentStatus.Completed,
    weatherMode: WeatherMode.W0,
  }
}

afterEach(() => {
  vi.restoreAllMocks()
  chartInstance.setOption.mockClear()
  chartInstance.resize.mockClear()
  chartInstance.dispose.mockClear()
})

describe('TASK-20 component coverage', () => {
  it('walks the import wizard into deterministic generic CSV mapping and duplicate policy', () => {
    render(
      <QueryClientProvider client={queryClient()}>
        <MemoryRouter><ImportWizardPage /></MemoryRouter>
      </QueryClientProvider>,
    )

    fireEvent.change(screen.getByLabelText('Профіль імпорту'), { target: { value: 'generic_csv' } })
    fireEvent.click(screen.getByRole('button', { name: 'Далі' }))
    const file = new File(['timestamp,energy_kwh\n2026-01-01T00:00:00Z,0.5\n'], 'fixture.csv', { type: 'text/csv' })
    fireEvent.change(screen.getByLabelText('CSV або TXT'), { target: { files: [file] } })
    fireEvent.click(screen.getByRole('button', { name: 'Далі' }))
    fireEvent.click(screen.getByRole('button', { name: 'Далі' }))

    expect(screen.getByRole('heading', { name: 'Відповідність колонок' })).toBeInTheDocument()
    expect(screen.getByLabelText('Часова колонка')).toHaveValue('timestamp')
    expect(screen.getByLabelText('Цільова колонка')).toHaveValue('energy_kwh')

    fireEvent.click(screen.getByRole('button', { name: 'Далі' }))
    fireEvent.click(screen.getByRole('button', { name: 'Далі' }))
    expect(screen.getByText('Конфліктний дублікат не зникає без явно обраної політики.')).toBeInTheDocument()
  })

  it('renders quality counters and submits the fixed transformation policy', async () => {
    vi.spyOn(api.datasets, 'getDataQualityReport').mockResolvedValue({
      createdAt: new Date('2026-08-08T00:00:00Z'),
      datasetVersionId: 'version-raw',
      engineVersion: 'quality-v1',
      expectedIntervalSeconds: 60,
      items: [],
      page: 1,
      pageSize: 100,
      reportId: 'report-1',
      reportVersion: 1,
      summary: { missing_values: 3, gap_count: 2, exact_duplicates: 1 },
      total: 0,
    })
    const transform = vi.spyOn(api.datasets, 'createTransformation').mockResolvedValue({
      jobId: 'job-transform',
      runId: 'run-1',
      sourceVersionId: 'version-raw',
      targetVersionId: 'version-hourly',
      status: 'queued',
    })

    renderRoute(
      '/dataset-versions/version-raw/quality',
      '/dataset-versions/:versionId/quality',
      <DataQualityPage />,
    )

    expect(await screen.findByRole('heading', { name: 'Якість даних' })).toBeInTheDocument()
    expect(screen.getByText('3')).toBeInTheDocument()
    expect(screen.getByText('2')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Створити погодинну версію' }))

    await waitFor(() => expect(transform).toHaveBeenCalledWith({
      versionId: 'version-raw',
      transformationCreate: {
        duplicatePolicy: 'reject',
        minimumHourCoverage: 0.9,
        shortGapLimitMinutes: 5,
      },
    }))
    expect(await screen.findByRole('status')).toHaveTextContent('job-transform')
  })

  it('renders the generated-contract model metrics table with baseline and recommendation', async () => {
    vi.spyOn(api.experiments, 'getExperiment').mockResolvedValue(completedExperiment())
    vi.spyOn(api.experiments, 'compareExperiment').mockResolvedValue({
      experimentId: 'exp-1',
      models: [
        {
          model_run_id: 'run-baseline',
          algorithm: AlgorithmType.SeasonalNaive24,
          status: 'completed',
          mean_cv_mae: 0.25,
          std_cv_mae: 0.02,
          final_mae: 0.24,
          final_rmse: 0.31,
          final_smape: 11,
          predict_ms_median: 0.5,
          is_recommended: false,
          horizon_metrics: [{ evaluation_scope: 'final_test', horizon: 1, mae: 0.2 }],
        },
        {
          model_run_id: 'run-ridge',
          algorithm: AlgorithmType.Ridge,
          status: 'completed',
          mean_cv_mae: 0.2,
          std_cv_mae: 0.01,
          final_mae: 0.19,
          final_rmse: 0.27,
          final_smape: 9,
          predict_ms_median: 1.2,
          is_recommended: true,
          horizon_metrics: [{ evaluation_scope: 'final_test', horizon: 1, mae: 0.18 }],
        },
      ],
    })

    renderRoute(
      '/experiments/exp-1/comparison',
      '/experiments/:experimentId/comparison',
      <ModelComparisonPage />,
    )

    expect(await screen.findByRole('heading', { name: 'Порівняння моделей' })).toBeInTheDocument()
    expect(screen.getByText(AlgorithmType.SeasonalNaive24)).toBeInTheDocument()
    expect(screen.getByText(AlgorithmType.Ridge)).toBeInTheDocument()
    expect(screen.getByText('рекомендована')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Створити прогноз рекомендованою моделлю' })).toHaveAttribute(
      'href',
      '/forecasts/new?datasetVersionId=version-hourly&modelRunId=run-ridge',
    )
  })

  it('keeps chart alternatives keyboard-focusable and disposes chart instances', () => {
    const view = render(<EChart option={{}} label="Тестовий графік" summary="Текстова альтернатива" />)
    const chart = screen.getByRole('img', { name: 'Тестовий графік' })

    chart.focus()
    expect(chart).toHaveFocus()
    expect(chart).toHaveAttribute('tabindex', '0')
    expect(screen.getByText('Текстова альтернатива')).toBeInTheDocument()

    view.unmount()
    expect(chartInstance.dispose).toHaveBeenCalledOnce()
  })
})
