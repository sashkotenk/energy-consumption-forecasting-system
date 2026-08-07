import { useMutation, useQuery } from '@tanstack/react-query'
import { Link, useParams } from 'react-router'
import { DuplicatePolicy } from '../generated/api/models'
import { api } from '../shared/api/client'
import { EmptyState, ErrorState, LoadingState, PageHeader, StatusBadge } from '../shared/ui/States'

function summaryValue(summary: Record<string, unknown>, keys: string[]) {
  for (const key of keys) {
    const value = summary[key]
    if (typeof value === 'number') return value
  }
  return 0
}

export function DataQualityPage() {
  const { versionId } = useParams()
  const report = useQuery({ queryKey: ['quality', versionId], queryFn: () => api.datasets.getDataQualityReport({ versionId: versionId!, page: 1, pageSize: 100 }), enabled: Boolean(versionId) })
  const transform = useMutation({ mutationFn: () => api.datasets.createTransformation({ versionId: versionId!, transformationCreate: { duplicatePolicy: DuplicatePolicy.Reject, minimumHourCoverage: 0.9, shortGapLimitMinutes: 5 } }) })
  if (report.isLoading) return <LoadingState label="Перевіряємо звіт якості…" />
  if (report.error) return <ErrorState error={report.error} retry={() => void report.refetch()} />
  if (!report.data) return <EmptyState title="Звіт якості відсутній" />
  const summary = report.data.summary as Record<string, unknown>
  const missing = summaryValue(summary, ['missing_values', 'missing_count', 'missing'])
  const gaps = summaryValue(summary, ['time_gaps', 'gap_count', 'gaps'])
  const duplicates = summaryValue(summary, ['duplicate_count', 'duplicates', 'exact_duplicates'])

  return (
    <>
      <PageHeader title="Якість даних" description={`Версія ${report.data.reportVersion} · рушій ${report.data.engineVersion}`} actions={<Link className="button" to={`/dataset-versions/${versionId}/analysis`}>До аналізу</Link>} />
      <section className="metric-grid" aria-label="Показники якості"><article className="metric-card"><span>Пропуски</span><strong>{missing}</strong><small>зафіксованих значень</small></article><article className="metric-card"><span>Часові розриви</span><strong>{gaps}</strong><small>послідовностей</small></article><article className="metric-card"><span>Дублікати</span><strong>{duplicates}</strong><small>виявлених міток</small></article><article className="metric-card"><span>Інтервал</span><strong>{report.data.expectedIntervalSeconds ?? '—'}</strong><small>секунд</small></article></section>
      <section className="panel"><div className="section-heading"><div><h2>Проблеми якості</h2><p>{report.data.total} груп проблем у звіті.</p></div></div>{report.data.items.length ? <div className="table-wrap"><table><caption>Згруповані проблеми якості</caption><thead><tr><th>Тип</th><th>Серйозність</th><th>Колонка</th><th>Кількість</th><th>Період</th></tr></thead><tbody>{report.data.items.map((issue) => <tr key={issue.id}><td>{issue.issueType}</td><td><StatusBadge value={issue.severity} /></td><td>{issue.columnName ?? '—'}</td><td>{issue.occurrenceCount}</td><td>{issue.rangeStart ? `${issue.rangeStart.toLocaleString('uk-UA')} — ${issue.rangeEnd?.toLocaleString('uk-UA') ?? '…'}` : '—'}</td></tr>)}</tbody></table></div> : <EmptyState title="Проблем не виявлено"><p>Звіт не містить груп проблем для цієї версії.</p></EmptyState>}</section>
      <section className="panel"><h2>Погодинна версія</h2><p>Основна політика: покриття щонайменше 90%, коротка інтерполяція до 5 хвилин і явне відхилення конфліктних дублікатів.</p>{transform.error && <ErrorState error={transform.error} />}{transform.data ? <p className="success-box" role="status">Перетворення поставлено в чергу. Завдання: <code>{transform.data.jobId}</code></p> : <button className="button primary" type="button" onClick={() => transform.mutate()} disabled={transform.isPending}>{transform.isPending ? 'Створюємо…' : 'Створити погодинну версію'}</button>}</section>
    </>
  )
}
