import { useMutation, useQuery } from '@tanstack/react-query'
import type { EChartsOption } from 'echarts'
import { useMemo } from 'react'
import { useForm } from 'react-hook-form'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router'
import { z } from 'zod'
import { ForecastExportFormat } from '../generated/api/models'
import { api } from '../shared/api/client'
import { downloadControlledArtifact } from '../shared/api/download'
import { EChart } from '../shared/ui/EChart'
import { EmptyState, ErrorState, LoadingState, PageHeader, StatusBadge } from '../shared/ui/States'

export function ForecastsPage() {
  const query = useQuery({ queryKey: ['forecasts'], queryFn: () => api.forecasts.listForecasts({ page: 1, pageSize: 50 }) })
  if (query.isLoading) return <LoadingState label="Завантажуємо прогнози…" />
  if (query.error) return <ErrorState error={query.error} retry={() => void query.refetch()} />
  return (
    <>
      <PageHeader title="Прогнози" description="Збережені 24-годинні прогнози з верифікованих model bundles." actions={<Link className="button primary" to="/forecasts/new">Новий прогноз</Link>} />
      {!query.data?.items.length ? <EmptyState title="Прогнозів ще немає"><p>Спочатку завершіть експеримент і оберіть рекомендований model run.</p><Link className="button" to="/experiments">До експериментів</Link></EmptyState> : <div className="table-wrap"><table><caption>Історія прогнозів</caption><thead><tr><th>Час походження</th><th>Алгоритм</th><th>Стан</th><th>Сума, кВт·год</th><th>Створено</th><th><span className="sr-only">Дії</span></th></tr></thead><tbody>{query.data.items.map((forecast) => <tr key={forecast.id}><td>{forecast.origin.toLocaleString('uk-UA')}</td><td>{forecast.algorithm}</td><td><StatusBadge value={forecast.status} /></td><td>{forecast.totalEnergyKwh.toFixed(3)}</td><td>{forecast.createdAt.toLocaleString('uk-UA')}</td><td><Link to={`/forecasts/${forecast.id}`}>Відкрити</Link></td></tr>)}</tbody></table></div>}
    </>
  )
}

const forecastSchema = z.object({
  datasetVersionId: z.string().trim().min(1, 'Вкажіть версію даних'),
  modelRunId: z.string().trim().min(1, 'Вкажіть model run'),
  origin: z.string(),
})
type ForecastValues = z.infer<typeof forecastSchema>

export function ForecastBuilderPage() {
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const { register, handleSubmit, setError, formState: { errors } } = useForm<ForecastValues>({ defaultValues: { datasetVersionId: params.get('datasetVersionId') ?? '', modelRunId: params.get('modelRunId') ?? '', origin: '' } })
  const create = useMutation({
    mutationFn: async (values: ForecastValues) => {
      const parsed = forecastSchema.safeParse(values)
      if (!parsed.success) {
        for (const issue of parsed.error.issues) setError(issue.path[0] as keyof ForecastValues, { message: issue.message })
        throw new Error('Перевірте параметри прогнозу.')
      }
      const origin = parsed.data.origin ? new Date(parsed.data.origin) : undefined
      if (origin && Number.isNaN(origin.getTime())) throw new Error('Некоректний час походження прогнозу.')
      return api.forecasts.createForecast({ forecastCreate: { datasetVersionId: parsed.data.datasetVersionId, modelRunId: parsed.data.modelRunId, origin } })
    },
    onSuccess: (forecast) => navigate(`/forecasts/${forecast.id}`),
  })
  return (
    <>
      <PageHeader title="Новий прогноз" description="Сформуйте рівно 24 погодинні значення на основі завершеного model run. Якщо origin не задано, backend обере останню допустиму завершену годину." />
      <form className="panel experiment-form" onSubmit={(event) => { void handleSubmit((values) => create.mutate(values))(event) }}>
        <div className="form-grid"><label>Версія даних<input {...register('datasetVersionId')} aria-invalid={Boolean(errors.datasetVersionId)} />{errors.datasetVersionId && <small className="field-error">{errors.datasetVersionId.message}</small>}</label><label>Model run<input {...register('modelRunId')} aria-invalid={Boolean(errors.modelRunId)} />{errors.modelRunId && <small className="field-error">{errors.modelRunId.message}</small>}</label><label>Origin (необов’язково)<input type="datetime-local" {...register('origin')} /></label></div>
        {create.error && <ErrorState error={create.error} />}
        <button className="button primary" type="submit" disabled={create.isPending}>{create.isPending ? 'Формуємо…' : 'Створити 24-годинний прогноз'}</button>
      </form>
    </>
  )
}

export function ForecastDetailsPage() {
  const { forecastId } = useParams()
  const query = useQuery({ queryKey: ['forecast', forecastId], queryFn: () => api.forecasts.getForecast({ forecastId: forecastId! }), enabled: Boolean(forecastId) })
  const exportResult = useMutation({
    mutationFn: async (format: ForecastExportFormat) => {
      const artifact = await api.exports.createForecastExport({ forecastId: forecastId!, forecastExportCreate: { format } })
      await downloadControlledArtifact(artifact)
    },
  })
  const chartOption = useMemo<EChartsOption>(() => ({
    tooltip: { trigger: 'axis' },
    legend: { data: ['Прогноз', 'Факт'] },
    xAxis: { type: 'category', data: query.data?.points.map((point) => point.targetTime.toLocaleString('uk-UA')) ?? [], axisLabel: { hideOverlap: true } },
    yAxis: { type: 'value', name: 'кВт·год' },
    series: [
      { name: 'Прогноз', type: 'line', data: query.data?.points.map((point) => point.predictedEnergyKwh) ?? [], symbolSize: 7 },
      { name: 'Факт', type: 'line', data: query.data?.points.map((point) => point.actualEnergyKwh) ?? [], symbolSize: 6, connectNulls: false },
    ],
  }), [query.data])

  if (query.isLoading) return <LoadingState label="Завантажуємо прогноз…" />
  if (query.error) return <ErrorState error={query.error} retry={() => void query.refetch()} />
  if (!query.data) return <EmptyState title="Прогноз не знайдено" />
  const forecast = query.data
  if (!forecast.points.length) return <EmptyState title="Прогноз не містить точок"><p>Збережений результат не має погодинних значень.</p></EmptyState>

  const actualCount = forecast.points.filter((point) => point.actualEnergyKwh !== null).length
  return (
    <>
      <PageHeader title="24-годинний прогноз" description={`${forecast.algorithm} · origin ${forecast.origin.toLocaleString('uk-UA')}`} actions={<Link className="button" to="/forecasts">До історії</Link>} />
      <section className="metric-grid" aria-label="Підсумок прогнозу"><article className="metric-card"><span>Очікуване споживання</span><strong>{forecast.totalEnergyKwh.toFixed(3)}</strong><small>кВт·год за 24 години</small></article><article className="metric-card"><span>Горизонт</span><strong>{forecast.points.length}</strong><small>погодинних значень</small></article><article className="metric-card"><span>Фактичні значення</span><strong>{actualCount}</strong><small>доступно для верифікації</small></article><article className="metric-card"><span>Стан</span><strong><StatusBadge value={forecast.status} /></strong><small>{forecast.timezone}</small></article></section>
      <EChart option={chartOption} label="Фактичне та прогнозоване погодинне енергоспоживання" summary={`Показано 24 прогнозовані точки; фактичні значення доступні для ${actualCount} точок. Таблиця нижче містить точні числові значення для screen reader і перевірки.`} />
      <section className="panel"><div className="table-wrap"><table><caption>Фактичні та прогнозовані значення</caption><thead><tr><th>h</th><th>Час</th><th>Прогноз, кВт·год</th><th>Факт, кВт·год</th><th>Абс. помилка</th></tr></thead><tbody>{forecast.points.map((point) => <tr key={point.horizon}><td>{point.horizon}</td><td>{point.targetTime.toLocaleString('uk-UA')}</td><td>{point.predictedEnergyKwh.toFixed(4)}</td><td>{point.actualEnergyKwh?.toFixed(4) ?? '—'}</td><td>{point.actualEnergyKwh === null ? '—' : Math.abs(point.actualEnergyKwh - point.predictedEnergyKwh).toFixed(4)}</td></tr>)}</tbody></table></div></section>
      <section className="panel"><h2>Експорт</h2><p>Файли спочатку створюються backend, а потім завантажуються через контрольований artifact endpoint. Внутрішній storage URL не використовується.</p><div className="inline-actions"><button type="button" onClick={() => exportResult.mutate(ForecastExportFormat.Csv)} disabled={exportResult.isPending}>Прогноз CSV</button><button type="button" onClick={() => exportResult.mutate(ForecastExportFormat.ChartJson)} disabled={exportResult.isPending}>Дані графіка JSON</button></div>{exportResult.error && <ErrorState error={exportResult.error} />}</section>
    </>
  )
}
