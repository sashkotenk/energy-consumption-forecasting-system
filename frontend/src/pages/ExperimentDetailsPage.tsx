import { useMutation, useQuery } from '@tanstack/react-query'
import { useEffect } from 'react'
import { Link, useParams } from 'react-router'
import { ExperimentExportFormat, ExperimentStatus } from '../generated/api/models'
import { api } from '../shared/api/client'
import { downloadControlledArtifact } from '../shared/api/download'
import { isTerminalJob, useJobPolling } from '../shared/query/useJobPolling'
import { EmptyState, ErrorState, LoadingState, PageHeader, StatusBadge } from '../shared/ui/States'

function isTerminalExperiment(status: ExperimentStatus) {
  return status === ExperimentStatus.Completed || status === ExperimentStatus.Cancelled || status === ExperimentStatus.Failed
}

function isActiveExperiment(status: ExperimentStatus) {
  return status === ExperimentStatus.Queued || status === ExperimentStatus.Running || status === ExperimentStatus.Cancelling
}

export function ExperimentDetailsPage() {
  const { experimentId } = useParams()
  const experiment = useQuery({
    queryKey: ['experiment', experimentId],
    queryFn: () => api.experiments.getExperiment({ experimentId: experimentId! }),
    enabled: Boolean(experimentId),
  })
  const job = useJobPolling(experiment.data?.jobId, Boolean(experiment.data) && !isTerminalExperiment(experiment.data!.status))

  useEffect(() => {
    if (isTerminalJob(job.data?.status)) void experiment.refetch()
  }, [job.data?.status]) // eslint-disable-line react-hooks/exhaustive-deps

  const cancel = useMutation({
    mutationFn: () => api.experiments.cancelExperiment({ experimentId: experimentId! }),
    onSuccess: async () => { await experiment.refetch(); await job.refetch() },
  })
  const retry = useMutation({
    mutationFn: () => api.jobs.retryJob({ jobId: experiment.data!.jobId }),
    onSuccess: async () => { await experiment.refetch(); await job.refetch() },
  })
  const exportManifest = useMutation({
    mutationFn: async () => {
      const artifact = await api.exports.createExperimentExport({ experimentId: experimentId!, experimentExportCreate: { format: ExperimentExportFormat.ManifestJson } })
      await downloadControlledArtifact(artifact)
    },
  })

  if (experiment.isLoading) return <LoadingState label="Завантажуємо експеримент…" />
  if (experiment.error) return <ErrorState error={experiment.error} retry={() => void experiment.refetch()} />
  if (!experiment.data) return <EmptyState title="Експеримент не знайдено" />

  const data = experiment.data
  const running = isActiveExperiment(data.status)
  const failed = data.status === ExperimentStatus.Failed
  const cancelled = data.status === ExperimentStatus.Cancelled
  const completed = data.status === ExperimentStatus.Completed

  return (
    <>
      <PageHeader title={data.name} description={`Експеримент ${data.id}`} actions={completed ? <Link className="button primary" to={`/experiments/${data.id}/comparison`}>Порівняти моделі</Link> : undefined} />
      <section className="metric-grid" aria-label="Стан експерименту">
        <article className="metric-card"><span>Стан</span><strong><StatusBadge value={data.status} /></strong><small>{job.data ? `job: ${job.data.status}` : 'стан запуску'}</small></article>
        <article className="metric-card"><span>Прогрес</span><strong>{job.data?.progressPct ?? (completed ? 100 : 0)}%</strong><small>фонова операція</small></article>
        <article className="metric-card"><span>Моделі</span><strong>{data.algorithms.length}</strong><small>разом із baseline</small></article>
        <article className="metric-card"><span>Режим</span><strong>{data.weatherMode}</strong><small>{data.sensitivityMode}</small></article>
      </section>

      {running && <section className="panel"><h2>Виконання</h2><progress max="100" value={job.data?.progressPct ?? 0} aria-label="Прогрес експерименту" /><p className="muted">Опитування сповільнюється від 1 до 5 секунд і автоматично припиняється після terminal state або демонтування сторінки.</p>{job.error && <ErrorState error={job.error} retry={() => void job.refetch()} />}<button type="button" onClick={() => cancel.mutate()} disabled={cancel.isPending || data.status === ExperimentStatus.Cancelling}>{data.status === ExperimentStatus.Cancelling ? 'Скасування…' : 'Скасувати експеримент'}</button></section>}

      {failed && <section className="state-card error" role="alert"><h2>Експеримент завершився помилкою</h2><p>{data.failureDetail ?? data.failureCode ?? 'Причина не була деталізована.'}</p>{retry.error && <p>{retry.error instanceof Error ? retry.error.message : 'Не вдалося повторити запуск.'}</p>}<button className="button primary" type="button" onClick={() => retry.mutate()} disabled={retry.isPending}>{retry.isPending ? 'Повторюємо…' : 'Повторити запуск'}</button></section>}
      {cancelled && <section className="state-card"><h2>Експеримент скасовано</h2><p>Скасований запуск є terminal state і більше не опитується.</p><button className="button primary" type="button" onClick={() => retry.mutate()} disabled={retry.isPending}>{retry.isPending ? 'Повторюємо…' : 'Запустити повторно'}</button></section>}

      <section className="panel"><h2>Конфігурація</h2><dl className="details-grid"><div><dt>Версія даних</dt><dd><code>{data.datasetVersionId}</code></dd></div><div><dt>Завдання</dt><dd><code>{data.jobId}</code></dd></div><div><dt>Алгоритми</dt><dd>{data.algorithms.join(', ')}</dd></div><div><dt>Створено</dt><dd>{data.createdAt.toLocaleString('uk-UA')}</dd></div><div><dt>Початок</dt><dd>{data.startedAt?.toLocaleString('uk-UA') ?? '—'}</dd></div><div><dt>Завершення</dt><dd>{data.finishedAt?.toLocaleString('uk-UA') ?? '—'}</dd></div></dl></section>

      {completed && <section className="panel"><h2>Результати</h2><p>Порівняння містить baseline, CV-метрики, фінальні показники рекомендованої моделі та MAE за горизонтом.</p><div className="inline-actions"><Link className="button primary" to={`/experiments/${data.id}/comparison`}>Відкрити порівняння</Link><button type="button" onClick={() => exportManifest.mutate()} disabled={exportManifest.isPending}>{exportManifest.isPending ? 'Готуємо…' : 'Завантажити manifest'}</button></div>{exportManifest.error && <ErrorState error={exportManifest.error} />}</section>}
    </>
  )
}
