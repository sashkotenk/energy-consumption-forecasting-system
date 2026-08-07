import type { ReactNode } from 'react'

export function LoadingState({ label = 'Завантаження даних…' }: { label?: string }) {
  return <div className="state-card loading" role="status" aria-live="polite">{label}</div>
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return <section className="state-card" aria-label={title}><h2>{title}</h2>{children && <div>{children}</div>}</section>
}

export function ErrorState({ error, retry }: { error: unknown; retry?: () => void }) {
  const message = error instanceof Error ? error.message : 'Невідома помилка'
  return (
    <section className="state-card error" role="alert">
      <h2>Не вдалося отримати дані</h2>
      <p>{message}</p>
      {retry && <button type="button" onClick={retry}>Повторити</button>}
    </section>
  )
}

export function StatusBadge({ value }: { value: string }) {
  return <span className={`status-badge status-${value.toLowerCase().replaceAll('_', '-')}`}>{value}</span>
}

export function PageHeader({ title, description, actions }: { title: string; description?: string; actions?: ReactNode }) {
  return (
    <header className="page-header">
      <div><h1>{title}</h1>{description && <p>{description}</p>}</div>
      {actions && <div className="page-actions">{actions}</div>}
    </header>
  )
}
