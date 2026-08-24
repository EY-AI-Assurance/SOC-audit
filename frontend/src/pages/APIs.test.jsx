import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import APIs from './APIs'
import { api } from '../api'

vi.mock('../api', () => ({
  api: {
    listApiProviders: vi.fn(),
    listApiConfigs: vi.fn(),
  },
}))

const providers = [
  { id: 'openai', label: 'OpenAI', protocol: 'openai_compatible', base_url: 'https://api.openai.com/v1' },
  { id: 'dify', label: 'Dify', protocol: 'dify', base_url: 'https://api.dify.ai/v1' },
]

describe('API Library', () => {
  afterEach(cleanup)

  beforeEach(() => {
    api.listApiProviders.mockResolvedValue({ providers })
    api.listApiConfigs.mockResolvedValue({
      configs: [],
      active: null,
    })
  })

  it('explains that a verified API is required', async () => {
    render(<MemoryRouter><APIs /></MemoryRouter>)

    expect(await screen.findByText('API Library')).toBeInTheDocument()
    expect(screen.getByText('No active API')).toBeInTheDocument()
    expect(screen.getByText('Your API library is empty')).toBeInTheDocument()
  })

  it('opens provider-guided API entry', async () => {
    render(<MemoryRouter><APIs /></MemoryRouter>)
    await screen.findByText('API Library')

    fireEvent.click(screen.getByRole('button', { name: '+ Add API' }))

    await waitFor(() => expect(screen.getByRole('heading', { name: 'Add API' })).toBeInTheDocument())
    expect(screen.getByRole('button', { name: 'OpenAI' })).toBeInTheDocument()
    expect(screen.getByLabelText('API key')).toHaveAttribute('type', 'password')
    expect(screen.getByText('Test & Activate')).toBeInTheDocument()
  })
})
