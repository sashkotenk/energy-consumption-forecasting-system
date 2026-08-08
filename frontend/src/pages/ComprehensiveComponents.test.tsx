import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import type { ReactNode } from 'react'
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

vi.mock('echarts/core', () => ({
  init: vi.fn(() => chartInstance),
  use: vi.fn(),
}))
vi.mock('echarts/charts', () => ({
  BarChart: {},
  HeatmapChart: {},
  LineChart: {},
}))
vi.mock('echarts/components', () => ({
  DataZoomComponent: {},
  GridComponent: {},
  LegendComponent: {},
  TooltipComponent: {},
  VisualMapComponent: {},
}))
vi.mock('echarts/renderers', () => ({ CanvasRenderer: {} }))

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
  cleanup()
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
    fireEvent.change(screen.getByLabelText(/CSV або TXT/), { target: { files: [file] } })
    fireEvent.click(screen.getByRole('button', { name: 'Далі' }))
    fireEvent.click(screen.getByRole('button', { name: 'Далі' }))

    expect(screen.getByRole('heading', { name: 'Відповідність колонок' })).toBeInTheDocument()
    expect(screen.getByLabelText('Часова колонка')).toHaveValue('timestamp')
    expect(screen.getByLabelText('Цільова колонка')).toHaveValue('energy_kwh')

    fireEvent.click(screen.getByRole('button', { name: 'Далі' }))
    fireEvent.click(screen.getByRole('button', { name: 'Далі' }))
    expect(screen.getByText('Конфліктний дублікат не зникає без явно обраної політики.')).toBeInTheDocument()
  })

  it('explains aggregate missing channels, submits the fixed policy, and opens the hourly version after success', async () => {
    const now = new Date('2026-08-08T00:00:00Z')
    vi.spyOn(api.datasets, 'getDataQualityReport').mockResolvedValue({
      createdAt: now,
      datasetVersionId: 'version-raw',
      engineVersion: 'quality-v1',
      expectedIntervalSeconds: 3600,
      items: [{
        id: 'missing-voltage',
        issueType: 'missing',
        severity: 'warning',
        columnName: 'voltage_v',
        occurrenceCount: 3,
        rangeStart: now,
        rangeEnd: now,
        evidence: {},
      }],
      page: 1,
      pageSize: 100,
      reportId: 'report-1',
      reportVersion: 1,
      summary: { missing_values: 3, gap_count: 0, exact_duplicates: 0 },
      total: 1,
    })
    const transform = vi.spyOn(api.datasets, 'createTransformation').mockResolvedValue({
      jobId: 'job-transform',
      runId: 'run-1',
      sourceVersionId: 'version-raw',
      targetVersionId: 'version-hourly',
      status: 'queued',
    })
    vi.spyOn(api.jobs, 'getJob').mockResolvedValue({
      attempt: 1,
      attempts: [],
      cancelRequestedAt: null,
      createdAt: now,
      errorCode: null,
      errorDetail: null,
      finishedAt: now,
      heartbeatAt: now,
      id: 'job-transform',
      jobType: JobType.DataTransformation,
      maxAttempts: 3,
      progressPct: 100,
      result: { target_version_id: 'version-hourly' },
      startedAt: now,
      status: JobStatus.Succeeded,
      updatedAt: now,
    })

    render(
      <QueryClientProvider client={queryClient()}>
        <MemoryRouter initialEntries={['/dataset-versions/version-raw/quality']}>
          <Routes>
            <Route path="/dataset-versions/:versionId/quality" element={<DataQualityPage />} />
            <Route path="/dataset-versions/:versionId/analysis" element={<h1>Аналіз погодинної версії</h1>} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    )

    expect(await screen.findByRole('heading', { name: 'Якість даних' })).toBeInTheDocument()
    const metrics = screen.getByRole('region', { name: 'Показники якості' })
    expect(within(metrics).getByText('Пропуски (усі канали)')).toBeInTheDocument()
    expect(within(metrics).getByText('3')).toBeInTheDocument()
    expect(screen.getByText(/необов’язкові електричні канали/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Підготувати погодинну версію' }))

    await waitFor(() => expect(transform).toHaveBeenCalledWith({
      versionId: 'version-raw',
      transformationCreate: {
        duplicatePolicy: 'reject',
        minimumHourCoverage: 0.9,
        shortGapLimitMinutes: 5,
      },
    }))
    expect(await screen.findByRole('heading', { name: 'Аналіз погодинної версії' })).toBeInTheDocument()
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
    expect(screen.getAllByText(AlgorithmType.SeasonalNaive24).length).toBeGreaterThan(0)
    expect(screen.getAllByText(AlgorithmType.Ridge).length).toBeGreaterThan(0)
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
