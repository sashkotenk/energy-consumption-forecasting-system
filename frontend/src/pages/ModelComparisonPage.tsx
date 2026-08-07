import { useMutation, useQuery } from '@tanstack/react-query'
import type { EChartsOption } from 'echarts'
import { useMemo } from 'react'
import { Link, useParams } from 'react-router'
import { AlgorithmType, ExperimentExportFormat } from '../generated/api/models'
import { api } from '../shared/api/client'
import { downloadControlledArtifact } from '../shared/api/download'
import { EChart } from '../shared/ui/EChart'
import { EmptyState, ErrorState, LoadingState, PageHeader, StatusBadge } from '../shared/ui/States'

function text(row: Record<string, unknown>, key: string) {
  const value = row[key]
  return typeof value === 'string' ? value : null
}

function number(row: Record<string, unknown>, key: string) {
  const value = row[key]
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function flag(row: Record<string, unknown>, key: string) {
  return row[key] === true
}

function metrics(row: Record<string, unknown>) {
  const value = row.horizon_metrics
  return Array.isArray(value) ? value.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object') : []
}

function metric(value: number | null, digits = 4) {
  return value === null ? '—' : value.toFixed(digits)
}

export function ModelComparisonPage() {
  const { experimentId } = useParams()
  const comparison = useQuery({ queryKey: ['experiment-comparison', experimentId], queryFn: () => api.experiments.compareExperiment({ experimentId: experimentId! }), enabled: Boolean(experimentId) })
  const experiment = useQuery({ queryKey: ['experiment', experimentId], queryFn: () => api.experiments.getExperiment({ experimentId: experimentId! }), enabled: Boolean(experimentId) })
  const exportResult = useMutation({
    mutationFn: async (format: ExperimentExportFormat) => {
      const artifact = await api.exports.createExperimentExport({ experimentId: experimentId!, experimentExportCreate: { format } })
      await downloadControlledArtifact(artifact)
    },
  })

  const rows = useMemo(() => (comparison.data?.models ?? []).filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object'), [comparison.data])
  const baseline = rows.find((row) => text(row, 'algorithm') === AlgorithmType.SeasonalNaive24)
  const recommended = rows.find((row) => flag(row, 'is_recommended'))
  const chartRows = useMemo(() => {
    const selected = [baseline, recommended].filter((row, index, array): row is Record<string, unknown> => Boolean(row) && array.indexOf(row) === index)
    return selected.map((row) => {
      const all = metrics(row)
      const final = all.filter((item) => String(item.evaluation_scope ?? '').toLowerCase().includes('final'))
      const points = (final.length ? final : all).map((item) => ({ horizon: number(item, 'horizon') ?? 0, mae: number(item, 'mae') })).filter((item) => item.horizon > 0 && item.mae !== null).sort((a, b) => a.horizon - b.horizon)
      return { algorithm: text(row, 'algorithm') ?? 'model', points }
    }).filter((row) => row.points.length)
  }, [baseline, recommended])

  const horizonOption = useMemo<EChartsOption>(() => ({
    tooltip: { trigger: 'axis' },
    legend: { data: chartRows.map((row) => row.algorithm) },
    xAxis: { type: 'category', name: 'Горизонт, год', data: Array.from({ length: 24 }, (_, index) => String(index + 1)) },
    yAxis: { type: 'value', name: 'MAE, кВт·год' },
    series: chartRows.map((row) => ({ name: row.algorithm, type: 'line', data: Array.from({ length: 24 }, (_, index) => row.points.find((point) => point.horizon === index + 1)?.mae ?? null), connectNulls: false })),
  }), [chartRows])

  if (comparison.isLoading || experiment.isLoading) return <LoadingState label="Формуємо порівняння моделей…" />
  const error = comparison.error ?? experiment.error
  if (error) return <ErrorState error={error} retry={() => { void comparison.refetch(); void experiment.refetch() }} />
  if (!comparison.data || !experiment.data) return <EmptyState title="Результати недоступні" />
  if (!baseline) return <ErrorState error={new Error('У порівнянні відсутній обов’язковий Seasonal Naive-24 baseline. Результат не можна трактувати як коректне порівняння.')} />

  const recommendedRunId = recommended ? text(recommended, 'model_run_id') : null

  return (
    <>
      <PageHeader title="Порівняння моделей" description={`Експеримент: ${experiment.data.name}. Усі рядки оцінюються на узгоджених хронологічних точках; baseline присутній явно.`} actions={<Link className="button" to={`/experiments/${experimentId}`}>До експерименту</Link>} />
      {!rows.length ? <EmptyState title="Порівняння порожнє"><p>Завершений експеримент ще не має збережених model runs.</p></EmptyState> : <>
        <section className="panel"><div className="section-heading"><div><h2>Метрики</h2><p>MAE є головною метрикою; RMSE і sMAPE — додаткові. `—` означає, що final test для цього model run не виконувався.</p></div></div><div className="table-wrap"><table><caption>Точність, стабільність і швидкість моделей</caption><thead><tr><th>Алгоритм</th><th>Стан</th><th>CV MAE</th><th>CV σ</th><th>Final MAE</th><th>RMSE</th><th>sMAPE</th><th>Predict, ms</th><th>Вибір</th></tr></thead><tbody>{rows.map((row, index) => <tr key={text(row, 'model_run_id') ?? `${text(row, 'algorithm')}-${index}`}><td><strong>{text(row, 'algorithm') ?? '—'}</strong></td><td><StatusBadge value={text(row, 'status') ?? 'unknown'} /></td><td>{metric(number(row, 'mean_cv_mae'))}</td><td>{metric(number(row, 'std_cv_mae'))}</td><td>{metric(number(row, 'final_mae'))}</td><td>{metric(number(row, 'final_rmse'))}</td><td>{metric(number(row, 'final_smape'), 2)}</td><td>{metric(number(row, 'predict_ms_median'), 2)}</td><td>{flag(row, 'is_recommended') ? <strong>рекомендована</strong> : '—'}</td></tr>)}</tbody></table></div></section>

        {chartRows.length ? <><EChart option={horizonOption} label="MAE за горизонтом для baseline та рекомендованої моделі" summary="Лінії показують зміну MAE для горизонтів 1–24. Якщо доступний final-test зріз, показано його; інакше — збережені horizon metrics." /><details className="panel"><summary>Таблична альтернатива MAE за горизонтом</summary><div className="table-wrap"><table><caption>MAE для горизонтів 1–24</caption><thead><tr><th>Горизонт</th>{chartRows.map((row) => <th key={row.algorithm}>{row.algorithm}</th>)}</tr></thead><tbody>{Array.from({ length: 24 }, (_, index) => index + 1).map((horizon) => <tr key={horizon}><td>{horizon}</td>{chartRows.map((row) => <td key={row.algorithm}>{metric(row.points.find((point) => point.horizon === horizon)?.mae ?? null)}</td>)}</tr>)}</tbody></table></div></details></> : <EmptyState title="MAE за горизонтом ще не збережено"><p>Таблиця загальних метрик залишається доступною.</p></EmptyState>}

        <section className="panel"><h2>Подальші дії</h2><div className="inline-actions">{recommendedRunId && <Link className="button primary" to={`/forecasts/new?datasetVersionId=${encodeURIComponent(experiment.data.datasetVersionId)}&modelRunId=${encodeURIComponent(recommendedRunId)}`}>Створити прогноз рекомендованою моделлю</Link>}<button type="button" onClick={() => exportResult.mutate(ExperimentExportFormat.MetricsCsv)} disabled={exportResult.isPending}>Метрики CSV</button><button type="button" onClick={() => exportResult.mutate(ExperimentExportFormat.MetricsJson)} disabled={exportResult.isPending}>Метрики JSON</button><button type="button" onClick={() => exportResult.mutate(ExperimentExportFormat.ManifestJson)} disabled={exportResult.isPending}>Manifest JSON</button></div>{exportResult.error && <ErrorState error={exportResult.error} />}</section>
      </>}
    </>
  )
}
