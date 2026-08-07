import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router'
import { api } from '../shared/api/client'
import { EmptyState, ErrorState, LoadingState, PageHeader, StatusBadge } from '../shared/ui/States'

export function ExperimentsPage() {
  const query = useQuery({
    queryKey: ['experiments'],
    queryFn: () => api.experiments.listExperiments({ page: 1, pageSize: 50 }),
  })

  if (query.isLoading) return <LoadingState label="Завантажуємо експерименти…" />
  if (query.error) return <ErrorState error={query.error} retry={() => void query.refetch()} />

  return (
    <>
      <PageHeader
        title="Експерименти"
        description="Хронологічні ML-запуски, їхній стан і конфігурація. Seasonal Naive-24 завжди входить до нового порівняння як baseline."
        actions={<Link className="button primary" to="/experiments/new">Новий експеримент</Link>}
      />
      {!query.data?.items.length ? (
        <EmptyState title="Експериментів ще немає">
          <p>Створіть перший запуск на підготовленій погодинній версії даних.</p>
          <Link className="button primary" to="/experiments/new">Створити експеримент</Link>
        </EmptyState>
      ) : (
        <div className="table-wrap">
          <table>
            <caption>Історія експериментів</caption>
            <thead><tr><th>Назва</th><th>Стан</th><th>Режим</th><th>Алгоритми</th><th>Створено</th><th><span className="sr-only">Дії</span></th></tr></thead>
            <tbody>
              {query.data.items.map((experiment) => (
                <tr key={experiment.id}>
                  <td><strong>{experiment.name}</strong><small className="table-note"><code>{experiment.id}</code></small></td>
                  <td><StatusBadge value={experiment.status} /></td>
                  <td>{experiment.weatherMode} · {experiment.sensitivityMode}</td>
                  <td>{experiment.algorithms.join(', ')}</td>
                  <td>{experiment.createdAt.toLocaleString('uk-UA')}</td>
                  <td><Link to={`/experiments/${experiment.id}`}>Деталі</Link></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  )
}
