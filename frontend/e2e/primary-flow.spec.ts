import { expect, test, type Page, type Route } from '@playwright/test'

const NOW = '2026-08-08T00:00:00Z'
const RAW_VERSION = 'version-raw'
const HOURLY_VERSION = 'version-hourly'
const EXPERIMENT_ID = 'exp-1'
const FORECAST_ID = 'forecast-1'

function json(route: Route, body: unknown, status = 200) {
  return route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
}

async function installSyntheticApi(page: Page) {
  await page.route('**/*', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const path = url.pathname
    const method = request.method()

    if (method === 'POST' && path === '/datasets') {
      return json(route, {
        id: 'dataset-1', name: 'Synthetic household', description: null,
        created_at: NOW, updated_at: NOW, version_count: 0,
      }, 201)
    }
    if (method === 'POST' && path === '/datasets/dataset-1/imports') {
      return json(route, { import_id: 'import-1', job_id: 'job-import', status: 'queued' }, 202)
    }
    if (method === 'GET' && path === '/jobs/job-import') {
      return json(route, {
        id: 'job-import', job_type: 'dataset_import', status: 'succeeded', priority: 0,
        payload: {}, result: {}, progress_pct: 100, attempt: 1, max_attempts: 3,
        error_code: null, error_detail: null, cancel_requested_at: null,
        created_at: NOW, updated_at: NOW, started_at: NOW, heartbeat_at: NOW, finished_at: NOW,
        attempts: [],
      })
    }
    if (method === 'GET' && path === '/dataset-imports/import-1') {
      return json(route, {
        id: 'import-1', dataset_id: 'dataset-1', dataset_version_id: RAW_VERSION,
        job_id: 'job-import', import_profile: 'generic_csv', status: 'completed',
        detected_format: { delimiter: ',', decimal_separator: '.' }, import_options: {},
        preview: {}, import_report: { rows: 48 }, created_at: NOW, completed_at: NOW,
      })
    }
    if (method === 'GET' && path === `/dataset-versions/${RAW_VERSION}/quality`) {
      return json(route, {
        report_id: 'report-1', dataset_version_id: RAW_VERSION, report_version: 1,
        engine_version: 'quality-v1', expected_interval_seconds: 3600,
        summary: { missing_values: 0, gap_count: 0, exact_duplicates: 0 },
        items: [], page: 1, page_size: 100, total: 0, created_at: NOW,
      })
    }
    if (method === 'POST' && path === `/dataset-versions/${RAW_VERSION}/transformations`) {
      return json(route, {
        run_id: 'transform-1', job_id: 'job-transform', source_version_id: RAW_VERSION,
        target_version_id: HOURLY_VERSION, status: 'queued',
      }, 202)
    }
    if (method === 'GET' && path === `/dataset-versions/${HOURLY_VERSION}/analytics/summary`) {
      return json(route, {
        dataset_version_id: HOURLY_VERSION, from: '2009-01-01T00:00:00Z', to: '2009-02-01T00:00:00Z',
        timezone: 'UTC', expected_hours: 744, stored_hours: 744, absent_hours: 0,
        energy_value_count: 744, missing_energy_hours: 0, total_energy_kwh: 372,
        mean_energy_kwh: 0.5, median_energy_kwh: 0.5, min_energy_kwh: 0.2,
        max_energy_kwh: 0.8, mean_coverage_ratio: 1, status_counts: { complete: 744 }, unit: 'kWh',
      })
    }
    if (method === 'GET' && path === `/dataset-versions/${HOURLY_VERSION}/analytics/series`) {
      return json(route, {
        dataset_version_id: HOURLY_VERSION, from: '2009-01-01T00:00:00Z', to: '2009-02-01T00:00:00Z',
        resolution: 'hour', timezone: 'UTC', unit: 'kWh', source_points: 2, returned_points: 2,
        downsampled: false,
        points: [
          { timestamp: '2009-01-01T00:00:00Z', energy_kwh: 0.4, mean_coverage_ratio: 1, quality_status: 'complete' },
          { timestamp: '2009-01-01T01:00:00Z', energy_kwh: 0.6, mean_coverage_ratio: 1, quality_status: 'complete' },
        ],
      })
    }
    if (method === 'GET' && (path.endsWith('/analytics/hourly-profile') || path.endsWith('/analytics/weekday-profile'))) {
      return json(route, {
        dataset_version_id: HOURLY_VERSION, from: '2009-01-01T00:00:00Z', to: '2009-02-01T00:00:00Z',
        timezone: 'UTC', unit: 'kWh',
        points: [{ key: 0, label: '0', sample_count: 31, total_energy_kwh: 15.5, mean_energy_kwh: 0.5, mean_coverage_ratio: 1 }],
      })
    }
    if (method === 'GET' && path.endsWith('/analytics/heatmap')) {
      return json(route, {
        dataset_version_id: HOURLY_VERSION, from: '2009-01-01T00:00:00Z', to: '2009-02-01T00:00:00Z',
        timezone: 'UTC', unit: 'kWh',
        points: [{ iso_weekday: 1, hour: 0, sample_count: 5, mean_energy_kwh: 0.5, mean_coverage_ratio: 1 }],
      })
    }
    if (method === 'GET' && path.endsWith('/analytics/distribution')) {
      return json(route, {
        dataset_version_id: HOURLY_VERSION, from: '2009-01-01T00:00:00Z', to: '2009-02-01T00:00:00Z',
        unit: 'kWh', sample_count: 744,
        bins: [{ lower_kwh: 0.2, upper_kwh: 0.8, sample_count: 744 }],
      })
    }
    if (method === 'GET' && path === '/algorithms') return json(route, [])
    if (method === 'POST' && path === '/experiments') {
      return json(route, { experiment_id: EXPERIMENT_ID, job_id: 'job-exp', status: 'queued' }, 202)
    }
    if (method === 'GET' && path === `/experiments/${EXPERIMENT_ID}`) {
      return json(route, {
        id: EXPERIMENT_ID, dataset_version_id: HOURLY_VERSION, job_id: 'job-exp',
        name: 'Synthetic comparison', status: 'completed', weather_mode: 'W0', sensitivity_mode: 'coverage_90',
        algorithms: ['seasonal_naive_24', 'ridge'], result_manifest: { schema: 'experiment-result/v1' },
        failure_code: null, failure_detail: null, created_at: NOW, started_at: NOW, finished_at: NOW,
      })
    }
    if (method === 'GET' && path === `/experiments/${EXPERIMENT_ID}/comparison`) {
      const horizons = Array.from({ length: 24 }, (_, index) => ({
        evaluation_scope: 'final_test', horizon: index + 1, mae: index === 0 ? 0.18 : 0.2,
      }))
      return json(route, {
        experiment_id: EXPERIMENT_ID,
        models: [
          { model_run_id: 'run-baseline', algorithm: 'seasonal_naive_24', status: 'completed', mean_cv_mae: 0.25, std_cv_mae: 0.02, final_mae: 0.24, final_rmse: 0.31, final_smape: 11, predict_ms_median: 0.5, is_recommended: false, horizon_metrics: horizons },
          { model_run_id: 'run-ridge', algorithm: 'ridge', status: 'completed', mean_cv_mae: 0.20, std_cv_mae: 0.01, final_mae: 0.19, final_rmse: 0.27, final_smape: 9, predict_ms_median: 1.2, is_recommended: true, horizon_metrics: horizons },
        ],
      })
    }
    if (method === 'POST' && path === '/forecasts') return json(route, forecastResponse(), 201)
    if (method === 'GET' && path === `/forecasts/${FORECAST_ID}`) return json(route, forecastResponse())
    if (method === 'POST' && path === `/forecasts/${FORECAST_ID}/exports`) {
      return json(route, {
        id: 'artifact-1', purpose: 'forecast_export', media_type: 'text/csv; charset=utf-8',
        filename: 'forecast.csv', size_bytes: 42, sha256: 'a'.repeat(64),
        download_url: '/artifacts/artifact-1/download', created_at: NOW,
      }, 201)
    }
    if (method === 'GET' && path === '/artifacts/artifact-1/download') {
      return route.fulfill({ status: 200, contentType: 'text/csv; charset=utf-8', body: 'horizon,predicted_energy_kwh\n1,0.5\n' })
    }

    return route.continue()
  })
}

function forecastResponse() {
  const points = Array.from({ length: 24 }, (_, index) => ({
    horizon: index + 1,
    target_time: new Date(Date.parse(NOW) + (index + 1) * 3_600_000).toISOString(),
    predicted_energy_kwh: 0.5,
    actual_energy_kwh: index < 2 ? 0.45 : null,
  }))
  return {
    id: FORECAST_ID, model_run_id: 'run-ridge', dataset_version_id: HOURLY_VERSION,
    artifact_id: 'model-artifact', bundle_sha256: 'b'.repeat(64), algorithm: 'ridge',
    feature_schema_version: 'base_v1', origin: NOW, timezone: 'UTC', status: 'completed',
    total_energy_kwh: 12, points, created_at: NOW, completed_at: NOW,
  }
}

test('synthetic primary flow covers import through controlled forecast export', async ({ page }) => {
  await installSyntheticApi(page)

  await page.goto('/datasets/new')
  await page.getByLabel('Профіль імпорту').selectOption('generic_csv')
  await page.getByRole('button', { name: 'Далі' }).click()
  await page.getByLabel('CSV або TXT').setInputFiles({
    name: 'synthetic-energy.csv',
    mimeType: 'text/csv',
    buffer: Buffer.from('timestamp,energy_kwh\n2026-01-01T00:00:00Z,0.50\n2026-01-01T01:00:00Z,0.55\n'),
  })
  for (let step = 0; step < 5; step += 1) await page.getByRole('button', { name: 'Далі' }).click()
  await page.getByRole('button', { name: 'Запустити імпорт' }).click()
  await expect(page.getByText('Імпорт завершено.')).toBeVisible()

  await page.getByRole('link', { name: 'Перевірити якість' }).click()
  await expect(page.getByRole('heading', { name: 'Якість даних' })).toBeVisible()
  await page.getByRole('button', { name: 'Створити погодинну версію' }).click()
  await expect(page.getByRole('status')).toContainText('job-transform')

  await page.goto(`/dataset-versions/${HOURLY_VERSION}/analysis`)
  await expect(page.getByRole('heading', { name: 'Аналіз споживання' })).toBeVisible()
  await expect(page.getByRole('img', { name: 'Графік погодинного споживання' })).toBeVisible()

  await page.goto(`/experiments/new?datasetVersionId=${HOURLY_VERSION}`)
  await expect(page.getByRole('heading', { name: 'Новий експеримент' })).toBeVisible()
  await page.getByRole('button', { name: 'Запустити експеримент' }).click()
  await expect(page).toHaveURL(new RegExp(`/experiments/${EXPERIMENT_ID}$`))
  await expect(page.getByRole('link', { name: 'Порівняти моделі' })).toBeVisible()

  await page.getByRole('link', { name: 'Порівняти моделі' }).click()
  await expect(page.getByRole('heading', { name: 'Порівняння моделей' })).toBeVisible()
  await expect(page.getByText('рекомендована')).toBeVisible()
  await page.getByRole('link', { name: 'Створити прогноз рекомендованою моделлю' }).click()

  await expect(page.getByRole('heading', { name: 'Новий прогноз' })).toBeVisible()
  await page.getByRole('button', { name: 'Створити 24-годинний прогноз' }).click()
  await expect(page).toHaveURL(new RegExp(`/forecasts/${FORECAST_ID}$`))
  await expect(page.getByRole('heading', { name: '24-годинний прогноз' })).toBeVisible()
  await expect(page.getByText('12.000')).toBeVisible()

  const download = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Прогноз CSV' }).click()
  const artifact = await download
  expect(artifact.suggestedFilename()).toBe('forecast.csv')
})
