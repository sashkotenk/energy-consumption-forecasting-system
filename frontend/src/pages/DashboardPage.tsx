import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router'
import { api } from '../shared/api/client'
import { ErrorState, LoadingState, PageHeader } from '../shared/ui/States'

export function DashboardPage() {
  const datasets = useQuery({ queryKey: ['datasets', 1], queryFn: () => api.datasets.listDatasets({ page: 1, pageSize: 5 }) })
  const experiments = useQuery({ queryKey: ['experiments', 1], queryFn: () => api.experiments.listExperiments({ page: 1, pageSize: 5 }) })
  const forecasts = useQuery({ queryKey: ['forecasts', 1], queryFn: () => api.forecasts.listForecasts({ page: 1, pageSize: 5 }) })

  if (datasets.isLoading || experiments.isLoading || forecasts.isLoading) return <LoadingState label="Формуємо огляд системи…" />
  const error = datasets.error ?? experiments.error ?? forecasts.error
  if (error) return <ErrorState error={error} retry={() => { void datasets.refetch(); void experiments.refetch(); void forecasts.refetch() }} />

  return (
    <>
      <PageHeader title="Огляд" description="Стан даних, експериментів і прогнозів в одному місці." actions={<Link className="button primary" to="/datasets/new">Імпортувати дані</Link>} />
      <section className="metric-grid" aria-label="Ключові показники">
        <article className="metric-card"><span>Набори даних</span><strong>{datasets.data?.total ?? 0}</strong><small>зареєстровано в системі</small></article>
        <article className="metric-card"><span>Експерименти</span><strong>{experiments.data?.total ?? 0}</strong><small>історія запусків</small></article>
        <article className="metric-card"><span>Прогнози</span><strong>{forecasts.data?.total ?? 0}</strong><small>24-годинні результати</small></article>
      </section>
      <section className="panel-grid">
        <article className="panel"><h2>Останні набори</h2>{datasets.data?.items.length ? <ul className="clean-list">{datasets.data.items.map((item) => <li key={item.id}><span><strong>{item.name}</strong><small>{item.versionCount} верс.</small></span><Link to={`/datasets/${item.id}`}>Відкрити</Link></li>)}</ul> : <p className="muted">Ще немає імпортованих наборів.</p>}</article>
        <article className="panel"><h2>Наступний крок</h2><p>Завантажте UCI або сумісний CSV, перевірте якість і створіть погодинну версію для аналізу.</p><Link className="text-link" to="/datasets/new">Відкрити майстер імпорту →</Link></article>
      </section>
    </>
  )
}
