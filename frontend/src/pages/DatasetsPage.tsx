import { useQuery } from '@tanstack/react-query'
import { Link, useParams } from 'react-router'
import { api } from '../shared/api/client'
import { EmptyState, ErrorState, LoadingState, PageHeader } from '../shared/ui/States'

export function DatasetsPage() {
  const query = useQuery({ queryKey: ['datasets'], queryFn: () => api.datasets.listDatasets({ page: 1, pageSize: 50 }) })
  if (query.isLoading) return <LoadingState label="Завантажуємо набори даних…" />
  if (query.error) return <ErrorState error={query.error} retry={() => void query.refetch()} />

  return (
    <>
      <PageHeader title="Набори даних" description="Каталог джерел і версій для аналізу та прогнозування." actions={<Link className="button primary" to="/datasets/new">Новий імпорт</Link>} />
      {!query.data?.items.length ? <EmptyState title="Наборів даних ще немає"><p>Почніть з UCI або завантажте сумісний CSV-файл.</p><Link className="button" to="/datasets/new">Імпортувати</Link></EmptyState> : (
        <div className="table-wrap"><table><caption>Зареєстровані набори даних</caption><thead><tr><th>Назва</th><th>Версії</th><th>Оновлено</th><th><span className="sr-only">Дії</span></th></tr></thead><tbody>{query.data.items.map((item) => <tr key={item.id}><td><strong>{item.name}</strong><small className="table-note">{item.description || 'Без опису'}</small></td><td>{item.versionCount}</td><td>{item.updatedAt.toLocaleString('uk-UA')}</td><td><Link to={`/datasets/${item.id}`}>Деталі</Link></td></tr>)}</tbody></table></div>
      )}
    </>
  )
}

export function DatasetDetailsPage() {
  const { datasetId } = useParams()
  const query = useQuery({ queryKey: ['dataset', datasetId], queryFn: () => api.datasets.getDataset({ datasetId: datasetId! }), enabled: Boolean(datasetId) })
  if (query.isLoading) return <LoadingState />
  if (query.error) return <ErrorState error={query.error} retry={() => void query.refetch()} />
  if (!query.data) return <EmptyState title="Набір не знайдено" />
  return <><PageHeader title={query.data.name} description={query.data.description ?? 'Набір даних EnergyForecast'} actions={<Link className="button primary" to={`/datasets/new?dataset=${query.data.id}`}>Додати версію</Link>} /><section className="panel"><dl className="details-grid"><div><dt>Ідентифікатор</dt><dd><code>{query.data.id}</code></dd></div><div><dt>Кількість версій</dt><dd>{query.data.versionCount}</dd></div><div><dt>Створено</dt><dd>{query.data.createdAt.toLocaleString('uk-UA')}</dd></div><div><dt>Оновлено</dt><dd>{query.data.updatedAt.toLocaleString('uk-UA')}</dd></div></dl><p className="muted">Після імпорту майстер надає ідентифікатор версії для переходу до звіту якості та аналітики.</p></section></>
}
