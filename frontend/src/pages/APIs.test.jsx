import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import APIs from './APIs'
import { api } from '../api'

vi.mock('../api', () => ({
  api: {
    listApiProviders: vi.fn(),
    listApiConfigs: vi.fn(),
    testApiConfig: vi.fn(),
    discoverModels: vi.fn(),
    createApiConfig: vi.fn(),
    activateApiConfig: vi.fn(),
  },
}))

const providers = [
  { id: 'openai', label: 'OpenAI', protocol: 'openai_compatible', base_url: 'https://api.openai.com/v1' },
  { id: 'bailian', label: 'Alibaba Bailian', protocol: 'openai_compatible', base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1' },
  { id: 'dify', label: 'Dify', protocol: 'dify', base_url: 'https://api.dify.ai/v1' },
]

describe('API Library', () => {
  afterEach(cleanup)

  beforeEach(() => {
    vi.clearAllMocks()
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

  it('requires only Base URL and API key', async () => {
    render(<MemoryRouter><APIs /></MemoryRouter>)
    await screen.findByText('API Library')

    fireEvent.click(screen.getByRole('button', { name: '+ Add API' }))

    await waitFor(() => expect(screen.getByRole('heading', { name: 'Add API' })).toBeInTheDocument())
    expect(screen.getByLabelText('Base URL')).toBeInTheDocument()
    expect(screen.getByLabelText('API key')).toHaveAttribute('type', 'password')
    expect(screen.queryByText('Provider')).not.toBeInTheDocument()
    expect(screen.queryByText('Configuration name')).not.toBeInTheDocument()
    expect(screen.getByText('Protocol, provider and model will be detected automatically.')).toBeInTheDocument()
    expect(screen.getByText('Test & Activate')).toBeInTheDocument()
  })

  it('automatically selects a model from only Base URL and API key', async () => {
    api.discoverModels.mockResolvedValue({
      models: ['text-embedding-v3', 'qwen-turbo', 'qwen-plus'],
      protocol: 'openai_compatible',
      provider: 'bailian',
    })
    api.createApiConfig.mockImplementation(async config => ({ id: 'config-1', ...config }))
    api.testApiConfig.mockResolvedValue({ status: 'verified' })
    api.activateApiConfig.mockResolvedValue({ is_active: true })

    render(<MemoryRouter><APIs /></MemoryRouter>)
    await screen.findByText('API Library')
    fireEvent.click(screen.getByRole('button', { name: '+ Add API' }))
    fireEvent.change(screen.getByLabelText('Base URL'), {
      target: { value: 'https://workspace.cn-beijing.maas.aliyuncs.com/compatible-mode/v1' },
    })
    fireEvent.change(screen.getByLabelText('API key'), { target: { value: 'sk-bailian-test' } })
    fireEvent.click(screen.getByRole('button', { name: 'Test & Activate' }))

    await waitFor(() => expect(api.createApiConfig).toHaveBeenCalledWith(expect.objectContaining({
      name: 'Alibaba Bailian',
      provider: 'bailian',
      base_url: 'https://workspace.cn-beijing.maas.aliyuncs.com/compatible-mode/v1',
      model: 'qwen-plus',
      api_key: 'sk-bailian-test',
    })))
    expect(api.discoverModels).toHaveBeenCalledWith({
      base_url: 'https://workspace.cn-beijing.maas.aliyuncs.com/compatible-mode/v1',
      api_key: 'sk-bailian-test',
      verify_tls: true,
    })
    expect(await screen.findByRole('status')).toHaveTextContent(
      'Alibaba Bailian passed the connection test and is now active.'
    )
  })

  it('shows a success message after a connection test passes', async () => {
    const config = {
      id: 'config-1',
      name: 'Free OpenRouter',
      provider: 'openai',
      base_url: 'https://openrouter.ai/api/v1',
      model: 'openrouter/free',
      masked_api_key: 'sk-o••••••••test',
      status: 'untested',
      is_active: false,
      last_tested_at: null,
      last_test_error: '',
    }
    api.listApiConfigs.mockResolvedValue({ configs: [config], active: null })
    api.testApiConfig.mockResolvedValue({ ...config, status: 'verified' })

    render(<MemoryRouter><APIs /></MemoryRouter>)
    await screen.findByText('Free OpenRouter')
    fireEvent.click(screen.getByRole('button', { name: 'Test' }))

    expect(await screen.findByRole('status')).toHaveTextContent(
      'Connection test passed for Free OpenRouter.'
    )
  })
})
