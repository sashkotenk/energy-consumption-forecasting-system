import { useQuery } from '@tanstack/react-query'
import type { EChartsOption } from 'echarts'
import { useMemo } from 'react'
import { useParams, useSearchParams } from 'react-router'
import { SeriesResolution } from '../generated/api/models'
import { api } from '../shared/api/client'
import { EChart } from '../shared/ui/EChart'
import { EmptyState, ErrorState, LoadingState, PageHeader } from '../shared/ui/States'

const weekdays = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Нд']

export function AnalysisPage() {
  const { versionId } = useParams()
  const [params, setParams] = useSearchParams()
  const fromText = params.get('from') ?? '2009-01-01'
  const toText = params.get('to') ?? '2009-02-01'
  const from = new Date(`${fromText}T00:00:00Z`)
  const to = new Date(`${toText}T00:00:00Z`)
  const enabled = Boolean(versionId) && Number.isFinite(from.getTime()) && Number.isFinite(to.getTime()) && from < to
  const request = { versionId: versionId!, from, to }
  const summary = useQuery({ queryKey: ['analytics-summary', versionId, fromText, toText], queryFn: () => api.analytics.getAnalyticsSummary(request), enabled })
  const series = useQuery({ queryKey: ['analytics-series', versionId, fromText, toText], queryFn: () => api.analytics.getEnergySeries({ ...request, resolution: SeriesResolution.Hour, maxPoints: 1200 }), enabled })
  const hourly = useQuery({ queryKey: ['analytics-hourly', versionId, fromText, toText], queryFn: () => api.analytics.getHourlyProfile(request), enabled })
  const weekday = useQuery({ queryKey: ['analytics-weekday', versionId, fromText, toText], queryFn: () => api.analytics.getWeekdayProfile(request), enabled })
  const heatmap = useQuery({ queryKey: ['analytics-heatmap', versionId, fromText, toText], queryFn: () => api.analytics.getEnergyHeatmap(request), enabled })
  const distribution = useQuery({ queryKey: ['analytics-distribution', versionId, fromText, toText], queryFn: () => api.analytics.getEnergyDistribution({ ...request, bins: 20 }), enabled })
  const queries = [summary, series, hourly, weekday, heatmap, distribution]
  const error = queries.find((query) => query.error)?.error
  const loading = queries.some((query) => query.isLoading)

  const seriesOption = useMemo<EChartsOption>(() => ({ tooltip: { trigger: 'axis' }, xAxis: { type: 'category', data: series.data?.points.map((point) => point.timestamp.toLocaleString('uk-UA')) ?? [], axisLabel: { hideOverlap: true } }, yAxis: { type: 'value', name: 'кВт·год' }, dataZoom: [{ type: 'inside' }, { type: 'slider' }], series: [{ name: 'Споживання', type: 'line', showSymbol: false, data: series.data?.points.map((point) => point.energyKwh) ?? [] }] }), [series.data])
  const hourlyOption = useMemo<EChartsOption>(() => ({ xAxis: { type: 'category', data: hourly.data?.points.map((point) => point.label) ?? [] }, yAxis: { type: 'value', name: 'кВт·год' }, tooltip: { trigger: 'axis' }, series: [{ type: 'bar', name: 'Середнє', data: hourly.data?.points.map((point) => point.meanEnergyKwh) ?? [] }] }), [hourly.data])
  const weekdayOption = useMemo<EChartsOption>(() => ({ xAxis: { type: 'category', data: weekday.data?.points.map((point) => point.label) ?? [] }, yAxis: { type: 'value', name: 'кВт·год' }, tooltip: { trigger: 'axis' }, series: [{ type: 'bar', name: 'Середнє', data: weekday.data?.points.map((point) => point.meanEnergyKwh) ?? [] }] }), [weekday.data])
  const heatmapOption = useMemo<EChartsOption>(() => ({ tooltip: {}, xAxis: { type: 'category', data: Array.from({ length: 24 }, (_, index) => String(index)) }, yAxis: { type: 'category', data: weekdays }, visualMap: { min: 0, max: Math.max(1, ...(heatmap.data?.points.map((point) => point.meanEnergyKwh) ?? [1])), calculable: true, orient: 'horizontal' }, series: [{ type: 'heatmap', data: heatmap.data?.points.map((point) => [point.hour, point.isoWeekday - 1, point.meanEnergyKwh]) ?? [] }] }), [heatmap.data])
  const distributionOption = useMemo<EChartsOption>(() => ({ xAxis: { type: 'category', data: distribution.data?.bins.map((bin) => `${bin.lowerKwh.toFixed(2)}–${bin.upperKwh.toFixed(2)}`) ?? [], axisLabel: { rotate: 35 } }, yAxis: { type: 'value', name: 'Кількість' }, tooltip: { trigger: 'axis' }, series: [{ type: 'bar', data: distribution.data?.bins.map((bin) => bin.sampleCount) ?? [] }] }), [distribution.data])

  return (
    <>
      <PageHeader title="Аналіз споживання" description="Часова поведінка, добова й тижнева сезонність, теплова карта та розподіл значень." />
      <form className="filter-bar" onSubmit={(event) => event.preventDefault()}><label>Від<input type="date" value={fromText} onChange={(event) => setParams({ from: event.target.value, to: toText })} /></label><label>До<input type="date" value={toText} onChange={(event) => setParams({ from: fromText, to: event.target.value })} /></label><span>Версія <code>{versionId}</code></span></form>
      {!enabled ? <EmptyState title="Некоректний період"><p>Оберіть дату завершення пізніше дати початку.</p></EmptyState> : loading ? <LoadingState label="Обчислюємо аналітичні зрізи…" /> : error ? <ErrorState error={error} retry={() => queries.forEach((query) => void query.refetch())} /> : !series.data?.points.length ? <EmptyState title="Немає даних у вибраному періоді"><p>Змініть межі періоду або перевірте якість версії.</p></EmptyState> : <>
        <section className="metric-grid" aria-label="Описова статистика">{Object.entries(summary.data ?? {}).filter(([, value]) => typeof value === 'number').slice(0, 4).map(([key, value]) => <article className="metric-card" key={key}><span>{key}</span><strong>{Number(value).toFixed(2)}</strong><small>показник вибраного періоду</small></article>)}</section>
        <EChart option={seriesOption} label="Графік погодинного споживання" summary={`${series.data.points.length} точок; ${series.data.downsampled ? 'дані проріджено для відображення.' : 'відображено всі доступні точки.'}`} />
        <div className="chart-grid"><EChart option={hourlyOption} label="Середнє споживання за годинами доби" summary="Стовпці показують середнє споживання для кожної години доби." /><EChart option={weekdayOption} label="Середнє споживання за днями тижня" summary="Стовпці показують середнє споживання для кожного дня тижня." /></div>
        <div className="chart-grid"><EChart option={heatmapOption} label="Теплова карта день тижня на годину" summary="Комірка показує середнє погодинне споживання для відповідної пари дня й години." /><EChart option={distributionOption} label="Розподіл погодинного споживання" summary={`Гістограма з ${distribution.data?.bins.length ?? 0} інтервалів.`} /></div>
        <details className="panel"><summary>Таблична альтернатива часовому графіку</summary><div className="table-wrap"><table><caption>Погодинні значення споживання</caption><thead><tr><th>Час</th><th>Енергія, кВт·год</th><th>Покриття</th><th>Якість</th></tr></thead><tbody>{series.data.points.slice(0, 200).map((point) => <tr key={point.timestamp.toISOString()}><td>{point.timestamp.toLocaleString('uk-UA')}</td><td>{point.energyKwh?.toFixed(4) ?? '—'}</td><td>{(point.meanCoverageRatio * 100).toFixed(1)}%</td><td>{point.qualityStatus}</td></tr>)}</tbody></table></div></details>
      </>}
    </>
  )
}
