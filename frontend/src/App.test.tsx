import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import App from './App'

describe('App', () => {
  it('renders the product shell and baseline status', () => {
    render(<App />)

    expect(screen.getByRole('heading', { name: 'EnergyForecast' })).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('Базову структуру застосунку підготовлено')
  })
})
