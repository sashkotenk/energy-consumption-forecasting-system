import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import { api } from './shared/api/client'

function renderApp(path = '/') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[path]}><App /></MemoryRouter></QueryClientProvider>)
}

afterEach(() => vi.restoreAllMocks())

describe('application shell', () => {
  it('renders dashboard success state from generated SDK clients', async () => {
    vi.spyOn(api.datasets, 'listDatasets').mockResolvedValue({ items: [], page: 1, pageSize: 5, total: 0 })
    vi.spyOn(api.experiments, 'listExperiments').mockResolvedValue({ items: [], page: 1, pageSize: 5, total: 0 })
    vi.spyOn(api.forecasts, 'listForecasts').mockResolvedValue({ items: [], page: 1, pageSize: 5, total: 0 })
    renderApp()
    expect(await screen.findByRole('heading', { name: 'Огляд' })).toBeInTheDocument()
    expect(screen.getAllByText('Набори даних').length).toBeGreaterThan(0)
    expect(screen.getByRole('link', { name: 'Імпортувати дані' })).toHaveAttribute('href', '/datasets/new')
  })

  it('shows a shared error state when a dashboard request fails', async () => {
    vi.spyOn(api.datasets, 'listDatasets').mockRejectedValue(new Error('service unavailable'))
    vi.spyOn(api.experiments, 'listExperiments').mockResolvedValue({ items: [], page: 1, pageSize: 5, total: 0 })
    vi.spyOn(api.forecasts, 'listForecasts').mockResolvedValue({ items: [], page: 1, pageSize: 5, total: 0 })
    renderApp()
    expect(await screen.findByRole('alert')).toHaveTextContent('service unavailable')
    expect(screen.getByRole('button', { name: 'Повторити' })).toBeInTheDocument()
  })
})
