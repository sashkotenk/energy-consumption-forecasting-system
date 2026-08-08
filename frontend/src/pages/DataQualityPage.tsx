import { useMutation, useQuery } from '@tanstack/react-query'
import { useEffect } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import { DuplicatePolicy, JobStatus } from '../generated/api/models'
import { api } from '../shared/api/client'
import { useJobPolling } from '../shared/query/useJobPolling'
import { EmptyState, ErrorState, LoadingState, PageHeader, StatusBadge } from '../shared/ui/States'

function summaryValue(summary: Record<string, unknown>, keys: string[]) {
  for (const key of keys) {
    const value = summary[key]
    if (typeof value === 'number') return value
  }
  return 0
}

const failedTransformationStatuses = new Set<string>([
  JobStatus.Cancelled,
  JobStatus.Failed,
  JobStatus.Stale,
])

export function DataQualityPage() {
  const { versionId } = useParams()
  const navigate = useNavigate()
  const report = useQuery({ queryKey: ['quality', versionId], queryFn: () => api.datasets.getDataQualityReport({ versionId: versionId!, page: 1, pageSize: 100 }), enabled: Boolean(versionId) })
  const transform = useMutation({ mutationFn: () => api.datasets.createTransformation({ versionId: versionId!, transformationCreate: { duplicatePolicy: DuplicatePolicy.Reject, minimumHourCoverage: 0.9, shortGapLimitMinutes: 5 } }) })
  const job = useJobPolling(transform.data?.jobId)
  const retry = useMutation({
    mutationFn: () => api.jobs.retryJob({ jobId: transform.data!.jobId }),
    onSuccess: async () => { await job.refetch() },
  })

  useEffect(() => {
    if (job.data?.status === JobStatus.Succeeded && transform.data?.targetVersionId) {
      navigate(`/dataset-versions/${transform.data.targetVersionId}/analysis`, { replace: true })
    }
  }, [job.data?.status, navigate, transform.data?.targetVersionId])

  if (report.isLoading) return <LoadingState label="Перевіряємо звіт якості…" />
  if (report.error) return <ErrorState error={report.error} retry={() => void report.refetch()} />
  if (!report.data) return <EmptyState title="Звіт якості відсутній" />
  const summary = report.data.summary as Record<string, unknown>
  const missing = summaryValue(summary, ['missing_values', 'missing_count', 'missing'])
  const gaps = summaryValue(summary, ['time_gaps', 'gap_count', 'gaps'])
  const duplicates = summaryValue(summary, ['duplicate_count', 'duplicates', 'exact_duplicates'])
  const transformationStatus = job.data?.status ?? transform.data?.status
  const transformationFailed = transformationStatus ? failedTransformationStatuses.has(transformationStatus) : false

  return (
    <>
      <PageHeader title="Якість даних" description={`Версія ${report.data.reportVersion} · рушій ${report.data.engineVersion}`} actions={<Link className="button" to="/datasets">До наборів даних</Link>} />
      <section className="metric-grid" aria-label="Показники якості"><article className="metric-card"><span>Пропуски (усі канали)</span><strong>{missing}</strong><small>сума по контрольованих полях</small></article><article className="metric-card"><span>Часові розриви</span><strong>{gaps}</strong><small>послідовностей</small></article><article className="metric-card"><span>Дублікати</span><strong>{duplicates}</strong><small>виявлених міток</small></article><article className="metric-card"><span>Інтервал</span><strong>{report.data.expectedIntervalSeconds ?? '—'}</strong><small>секунд</small></article></section>
      <section className="panel"><div className="section-heading"><div><h2>Проблеми якості</h2><p>{report.data.total} груп проблем у звіті.</p></div></div>{missing > 0 && <p className="muted">Для користувацького CSV сумарний лічильник може включати необов’язкові електричні канали, яких немає у файлі. Оцінюйте вплив за конкретною колонкою та серйозністю проблеми; відсутність додаткового каналу не означає відсутність цільового ряду.</p>}{report.data.items.length ? <div className="table-wrap"><table><caption>Згруповані проблеми якості</caption><thead><tr><th>Тип</th><th>Серйозність</th><th>Колонка</th><th>Кількість</th><th>Період</th></tr></thead><tbody>{report.data.items.map((issue) => <tr key={issue.id}><td>{issue.issueType}</td><td><StatusBadge value={issue.severity} /></td><td>{issue.columnName ?? '—'}</td><td>{issue.occurrenceCount}</td><td>{issue.rangeStart ? `${issue.rangeStart.toLocaleString('uk-UA')} — ${issue.rangeEnd?.toLocaleString('uk-UA') ?? '…'}` : '—'}</td></tr>)}</tbody></table></div> : <EmptyState title="Проблем не виявлено"><p>Звіт не містить груп проблем для цієї версії.</p></EmptyState>}</section>
      <section className="panel"><h2>Погодинна версія</h2><p>Основна політика: покриття щонайменше 90%, коротка інтерполяція до 5 хвилин і явне відхилення конфліктних дублікатів. Після успішного завершення система автоматично відкриє аналіз нової погодинної версії.</p>{transform.error && <ErrorState error={transform.error} />}{!transform.data ? <button className="button primary" type="button" onClick={() => transform.mutate()} disabled={transform.isPending}>{transform.isPending ? 'Ставимо в чергу…' : 'Підготувати погодинну версію'}</button> : transformationFailed ? <div className="state-card error" role="alert"><h3>Не вдалося створити погодинну версію</h3><p>{job.data?.errorDetail ?? `Завдання завершилося зі станом ${transformationStatus}.`}</p>{retry.error && <p>{retry.error instanceof Error ? retry.error.message : 'Не вдалося повторити завдання.'}</p>}<button className="button primary" type="button" onClick={() => retry.mutate()} disabled={retry.isPending}>{retry.isPending ? 'Повторюємо…' : 'Повторити перетворення'}</button></div> : <div className="success-box" role="status" aria-live="polite"><strong>Готуємо погодинну версію…</strong><p>Стан: <StatusBadge value={transformationStatus ?? 'queued'} /> · прогрес {job.data?.progressPct ?? 0}%</p><progress max="100" value={job.data?.progressPct ?? 0} aria-label="Прогрес підготовки погодинної версії" /><p className="muted">Цільова версія: <code>{transform.data.targetVersionId}</code>. Після завершення перехід до її аналізу відбудеться автоматично.</p>{job.error && <ErrorState error={job.error} retry={() => void job.refetch()} />}</div>}</section>
    </>
  )
}
