import { useCallback, useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import ConfirmDialog from '../components/ConfirmDialog'

const EMPTY_FORM = {
  name: '',
  provider: '',
  base_url: '',
  api_key: '',
  model: '',
  dify_user: 'soc-audit-local',
  verify_tls: true,
}

const PREFERRED_MODELS = {
  openrouter: ['openrouter/free'],
  bailian: ['qwen-plus', 'qwen-turbo'],
  deepseek: ['deepseek-chat', 'deepseek-v4-flash'],
  openai: ['gpt-4o-mini', 'gpt-4.1-mini'],
}

const NON_CHAT_MODEL_WORDS = [
  'embedding', 'rerank', 'moderation', 'whisper', 'transcribe', 'tts',
  'speech', 'image', 'dall-e', 'realtime',
]

function chooseAutomaticModel(provider, models) {
  const preferred = PREFERRED_MODELS[provider] || []
  for (const model of preferred) {
    if (models.includes(model)) return model
  }
  if (provider === 'openrouter') {
    const freeModel = models.find(model => model.endsWith(':free'))
    if (freeModel) return freeModel
  }
  return models.find(model => !NON_CHAT_MODEL_WORDS.some(word => model.toLowerCase().includes(word))) || models[0] || ''
}

function formatDate(iso) {
  if (!iso) return 'Never'
  return new Date(iso).toLocaleString('zh-CN', {
    month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
  })
}

function ConfigCard({ config, provider, busy, onEdit, onTest, onActivate, onDelete }) {
  const verified = config.status === 'verified'
  return (
    <div className={`bg-white rounded-xl border p-5 shadow-sm ${config.is_active ? 'border-[#FFE600] ring-1 ring-[#FFE600]' : 'border-gray-200'}`}>
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <h2 className="font-semibold text-gray-900">{config.name}</h2>
            <span className="text-xs px-2 py-0.5 rounded-full bg-gray-100 text-gray-600">{provider?.label || config.provider}</span>
            {config.is_active && <span className="text-xs px-2 py-0.5 rounded-full bg-[#FFE600] text-[#2E2E38] font-semibold">Active</span>}
          </div>
          <p className="text-xs text-gray-400 mt-1 truncate">{config.base_url}</p>
        </div>
        <span className={`shrink-0 text-xs font-medium px-2.5 py-1 rounded-full ${verified ? 'bg-green-100 text-green-700' : config.last_test_error ? 'bg-red-100 text-red-700' : 'bg-amber-100 text-amber-700'}`}>
          {verified ? '● Verified' : config.last_test_error ? '● Test failed' : '● Needs verification'}
        </span>
      </div>

      <div className="grid sm:grid-cols-3 gap-3 mt-4 text-xs">
        <div><p className="text-gray-400">Default model</p><p className="text-gray-700 mt-0.5 truncate">{config.model || 'Managed by Dify'}</p></div>
        <div><p className="text-gray-400">API key</p><p className="text-gray-700 mt-0.5 font-mono">{config.masked_api_key}</p></div>
        <div><p className="text-gray-400">Last tested</p><p className="text-gray-700 mt-0.5">{formatDate(config.last_tested_at)}</p></div>
      </div>

      {config.last_test_error && !verified && (
        <p className="text-xs text-red-600 bg-red-50 rounded-lg px-3 py-2 mt-3">{config.last_test_error}</p>
      )}

      <div className="flex items-center justify-end gap-2 mt-4 pt-3 border-t border-gray-100">
        <button onClick={onEdit} className="text-xs px-3 py-1.5 rounded-lg text-gray-600 hover:bg-gray-100">Edit</button>
        <button disabled={busy} onClick={onTest} className="text-xs px-3 py-1.5 rounded-lg border border-gray-200 text-gray-700 hover:bg-gray-50 disabled:opacity-50">Test</button>
        {!config.is_active && (
          <button disabled={!verified || busy} onClick={onActivate} className="text-xs px-3 py-1.5 rounded-lg bg-[#2E2E38] text-white disabled:opacity-30">Activate</button>
        )}
        <button onClick={onDelete} className="text-xs px-2 py-1.5 text-gray-300 hover:text-red-500">Delete</button>
      </div>
    </div>
  )
}

function ConfigEditor({ providers, initial, onClose, onSaved }) {
  const editing = Boolean(initial)
  const [form, setForm] = useState(initial ? {
    name: initial.name,
    provider: initial.provider,
    base_url: initial.base_url,
    api_key: '',
    model: initial.model,
    dify_user: initial.dify_user || 'soc-audit-local',
    verify_tls: initial.verify_tls,
  } : EMPTY_FORM)
  const [models, setModels] = useState(initial?.model ? [initial.model] : [])
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const selectedProvider = providers.find(item => item.id === form.provider)
  const isDify = form.provider === 'dify'

  const change = (key, value) => setForm(current => ({ ...current, [key]: value }))

  const changeBaseUrl = (baseUrl) => {
    setForm(current => ({ ...current, base_url: baseUrl, provider: '', model: '' }))
    setModels([])
  }

  const modelDiscoveryRequest = () => {
    if (!form.api_key && !editing) return setError('Enter an API key before loading models.')
    const unchangedConnection = editing
      && !form.api_key
      && form.base_url === initial.base_url
    if (editing && !form.api_key && !unchangedConnection) {
      throw new Error('Enter the API key again after changing the Base URL.')
    }
    return unchangedConnection ? {
      config_id: initial.id,
    } : {
      base_url: form.base_url,
      api_key: form.api_key,
      verify_tls: form.verify_tls,
    }
  }

  const applyDiscovery = (result) => {
    const providerId = result.provider || 'custom_openai_compatible'
    const protocol = result.protocol || 'openai_compatible'
    const availableModels = result.models || []
    const selectedModel = protocol === 'dify'
      ? ''
      : form.model || chooseAutomaticModel(providerId, availableModels)
    setModels(availableModels)
    setForm(current => ({
      ...current,
      provider: providerId,
      model: selectedModel,
    }))
    return { providerId, protocol, selectedModel }
  }

  const discover = async () => {
    setBusy('models')
    setError('')
    try {
      const request = modelDiscoveryRequest()
      if (!request) return ''
      const result = await api.discoverModels(request)
      const detected = applyDiscovery(result)
      if (detected.protocol !== 'dify' && !detected.selectedModel) {
        setShowAdvanced(true)
        setError('No chat models were returned. Enter the model ID under Advanced settings.')
      }
      return detected
    } catch (e) {
      setShowAdvanced(true)
      setError(`${e.message} Enter the model ID under Advanced settings.`)
      return ''
    } finally {
      setBusy('')
    }
  }

  const save = async (activate) => {
    if (!editing && !form.api_key.trim()) return setError('API key is required.')
    if (!form.base_url.trim()) return setError('Base URL is required.')
    setBusy(activate ? 'activate' : 'save')
    setError('')
    try {
      if (!activate) {
        const providerId = form.provider || initial?.provider || 'auto'
        const name = form.name.trim() || initial?.name || 'API configuration'
        const payload = { ...form, name, provider: providerId, model: form.model.trim() }
        if (editing && !payload.api_key) delete payload.api_key
        if (editing) {
          await api.updateApiConfig(initial.id, payload)
        } else {
          await api.createApiConfig(payload)
        }
        onSaved(`${name} was saved without testing the connection.`)
        return
      }

      let providerId = form.provider || initial?.provider || ''
      let protocol = selectedProvider?.protocol || initial?.protocol || ''
      let model = form.model.trim()
      const shouldDetect = !editing
        || Boolean(form.api_key.trim())
        || form.base_url !== initial.base_url
      if (shouldDetect) {
        try {
          const request = modelDiscoveryRequest()
          const result = await api.discoverModels(request)
          const detected = applyDiscovery(result)
          providerId = detected.providerId
          protocol = detected.protocol
          model = detected.selectedModel
        } catch (e) {
          setShowAdvanced(true)
          setError(e.message)
          return
        }
      }
      if (protocol !== 'dify' && !model) {
        setShowAdvanced(true)
        setError('This API did not return a model list. Enter the Model ID under Advanced settings.')
        return
      }
      const provider = providers.find(item => item.id === providerId)
      const name = form.name.trim() || provider?.label || 'API configuration'
      const payload = { ...form, name, provider: providerId, model }
      if (editing && !payload.api_key) delete payload.api_key
      const saved = editing
        ? await api.updateApiConfig(initial.id, payload)
        : await api.createApiConfig(payload)
      await api.testApiConfig(saved.id)
      await api.activateApiConfig(saved.id)
      onSaved(`${name} passed the connection test and is now active.`)
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy('')
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-2xl w-full max-w-xl shadow-xl max-h-[92vh] flex flex-col">
        <div className="px-6 py-4 border-b border-gray-100 flex items-center justify-between">
          <div><h2 className="font-bold text-lg text-[#2E2E38]">{editing ? 'Edit API' : 'Add API'}</h2><p className="text-xs text-gray-400 mt-0.5">Only Base URL and API key are required.</p></div>
          <button onClick={onClose} className="text-xl text-gray-400 hover:text-gray-600">×</button>
        </div>
        <div className="px-6 py-5 overflow-y-auto flex flex-col gap-4">
          <div>
            <label className="block text-xs font-semibold text-gray-600 mb-1">Base URL</label>
            <input aria-label="Base URL" value={form.base_url} onChange={e => changeBaseUrl(e.target.value)} placeholder="https://your-api-host/compatible-mode/v1" className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-[#FFE600]" />
            <p className="text-xs text-gray-400 mt-1">Paste the complete API address provided by your service.</p>
          </div>
          <div>
            <label className="block text-xs font-semibold text-gray-600 mb-1">API key</label>
            <input aria-label="API key" type="password" value={form.api_key} onChange={e => change('api_key', e.target.value)} placeholder={editing ? 'Leave blank to keep the current key' : 'Paste API key'} autoComplete="new-password" className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-[#FFE600]" />
          </div>
          {form.provider && (
            <p className="text-xs text-gray-400 bg-gray-50 rounded-lg px-3 py-2">
              Detected automatically: {selectedProvider?.label || 'OpenAI-compatible API'}
              {form.model ? ` · ${form.model}` : ''}
            </p>
          )}
          {!form.provider && (
            <p className="text-xs text-gray-400 bg-gray-50 rounded-lg px-3 py-2">Protocol, provider and model will be detected automatically.</p>
          )}
          <button onClick={() => setShowAdvanced(value => !value)} className="text-xs text-gray-500 text-left hover:text-gray-800">{showAdvanced ? '▾' : '▸'} Advanced settings (optional)</button>
          {showAdvanced && (
            <div className="flex flex-col gap-4 rounded-xl border border-gray-100 bg-gray-50/60 p-4">
              <div>
                <label className="block text-xs font-semibold text-gray-600 mb-1">Configuration name <span className="font-normal text-gray-400">(optional)</span></label>
                <input value={form.name} onChange={e => change('name', e.target.value)} placeholder={selectedProvider?.label || 'API configuration'} className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#FFE600]" />
              </div>
              {!isDify && (
                <div>
                  <div className="flex items-center justify-between mb-1">
                    <label className="text-xs font-semibold text-gray-600">Model <span className="font-normal text-gray-400">(automatic)</span></label>
                    <button onClick={discover} disabled={Boolean(busy)} className="text-xs text-blue-500 hover:underline disabled:opacity-50">{busy === 'models' ? 'Loading…' : 'Load models'}</button>
                  </div>
                  {models.length > 0 ? (
                    <select value={form.model} onChange={e => change('model', e.target.value)} className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#FFE600]">
                      {!models.includes(form.model) && form.model && <option value={form.model}>{form.model}</option>}
                      {models.map(model => <option key={model} value={model}>{model}</option>)}
                    </select>
                  ) : (
                    <input value={form.model} onChange={e => change('model', e.target.value)} placeholder="Only needed if automatic selection fails" className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-[#FFE600]" />
                  )}
                </div>
              )}
              {isDify && (
                <div>
                  <label className="block text-xs font-semibold text-gray-600 mb-1">Dify user identifier <span className="font-normal text-gray-400">(optional)</span></label>
                  <input value={form.dify_user} onChange={e => change('dify_user', e.target.value)} className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#FFE600]" />
                </div>
              )}
              <label className="flex items-start gap-2 text-xs text-gray-600 cursor-pointer">
                <input type="checkbox" checked={form.verify_tls} onChange={e => change('verify_tls', e.target.checked)} className="mt-0.5 accent-[#2E2E38]" />
                <span><strong>Verify TLS certificates</strong><br /><span className="text-gray-400">Keep enabled unless an internal API uses a company certificate not trusted by this computer.</span></span>
              </label>
            </div>
          )}
          {error && <p className="text-xs text-red-600 bg-red-50 rounded-lg px-3 py-2">{error}</p>}
        </div>
        <div className="px-6 py-4 border-t border-gray-100 flex items-center justify-between gap-3">
          <button onClick={onClose} className="text-sm text-gray-500">Cancel</button>
          <div className="flex gap-2">
            <button disabled={Boolean(busy)} onClick={() => save(false)} className="text-sm px-4 py-2 border border-gray-200 rounded-lg text-gray-700 disabled:opacity-50">{busy === 'save' ? 'Saving…' : 'Save without activating'}</button>
            <button disabled={Boolean(busy)} onClick={() => save(true)} className="text-sm px-4 py-2 bg-[#FFE600] rounded-lg font-semibold text-[#2E2E38] disabled:opacity-50">{busy === 'activate' ? 'Testing…' : 'Test & Activate'}</button>
          </div>
        </div>
      </div>
    </div>
  )
}

export default function APIs() {
  const [providers, setProviders] = useState([])
  const [configs, setConfigs] = useState([])
  const [active, setActive] = useState(null)
  const [editor, setEditor] = useState(null)
  const [showEditor, setShowEditor] = useState(false)
  const [confirmId, setConfirmId] = useState(null)
  const [busyId, setBusyId] = useState('')
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  const providersById = useMemo(() => Object.fromEntries(providers.map(item => [item.id, item])), [providers])

  const load = useCallback(async () => {
    try {
      const [providerData, configData] = await Promise.all([api.listApiProviders(), api.listApiConfigs()])
      setProviders(providerData.providers || [])
      setConfigs(configData.configs || [])
      setActive(configData.active || null)
      window.dispatchEvent(new Event('api-config-changed'))
    } catch (e) {
      setError(e.message)
    }
  }, [])

  useEffect(() => {
    const timer = window.setTimeout(load, 0)
    return () => window.clearTimeout(timer)
  }, [load])

  const test = async (id) => {
    setBusyId(id)
    setError('')
    setSuccess('')
    try {
      await api.testApiConfig(id)
      const config = configs.find(item => item.id === id)
      setSuccess(`Connection test passed${config ? ` for ${config.name}` : ''}.`)
    } catch (e) {
      setError(e.message)
    } finally {
      setBusyId('')
      await load()
    }
  }

  const activate = async (id) => {
    setBusyId(id)
    setError('')
    setSuccess('')
    try {
      await api.activateApiConfig(id)
      const config = configs.find(item => item.id === id)
      setSuccess(`${config?.name || 'API configuration'} is now active.`)
      await load()
    } catch (e) {
      setError(e.message)
    } finally {
      setBusyId('')
    }
  }

  const remove = async () => {
    try { await api.deleteApiConfig(confirmId); await load() } catch (e) { setError(e.message) } finally { setConfirmId(null) }
  }

  const saved = async (message = '') => {
    setShowEditor(false)
    setEditor(null)
    setError('')
    setSuccess(message)
    await load()
  }

  return (
    <div>
      <div className="flex items-start justify-between gap-4 mb-6">
        <div>
          <h1 className="text-xl font-bold text-[#2E2E38]">API Library</h1>
          <p className="text-sm text-gray-400 mt-1">Save trusted LLM connections and choose one for new audit jobs.</p>
        </div>
        <button onClick={() => { setEditor(null); setShowEditor(true) }} className="shrink-0 px-4 py-2 bg-[#FFE600] text-[#2E2E38] text-sm font-semibold rounded-lg hover:bg-yellow-300">+ Add API</button>
      </div>

      <div className={`rounded-xl px-4 py-3 mb-6 border flex items-center gap-3 ${active ? 'bg-green-50 border-green-100' : 'bg-amber-50 border-amber-200'}`}>
        <span className={`h-2.5 w-2.5 rounded-full ${active ? 'bg-green-500' : 'bg-amber-400'}`} />
        <div>
          <p className="text-xs font-semibold text-gray-700">{active ? 'Active API' : 'No active API'}</p>
          <p className="text-xs text-gray-500 mt-0.5">{active ? `${active.name}${active.model ? ` / ${active.model}` : ''} will be locked when each new job starts.` : 'Test and activate a configuration before running a job.'}</p>
        </div>
      </div>

      {error && <p className="text-sm text-red-500 bg-red-50 rounded-lg px-4 py-3 mb-4">{error}</p>}
      {success && (
        <div role="status" className="text-sm text-green-700 bg-green-50 border border-green-200 rounded-lg px-4 py-3 mb-4 flex items-center justify-between gap-4">
          <span>✓ {success}</span>
          <button onClick={() => setSuccess('')} aria-label="Dismiss success message" className="text-green-500 hover:text-green-800">×</button>
        </div>
      )}

      {configs.length === 0 ? (
        <div className="bg-white border border-dashed border-gray-300 rounded-2xl text-center py-16 px-6">
          <div className="mx-auto h-12 w-12 rounded-xl bg-yellow-50 flex items-center justify-center text-xl mb-3">⌁</div>
          <p className="font-semibold text-gray-700">Your API library is empty</p>
          <p className="text-sm text-gray-400 mt-1">Choose a provider, paste a key, and the app will help select a model.</p>
        </div>
      ) : (
        <div className="grid gap-4">
          {configs.map(config => (
            <ConfigCard key={config.id} config={config} provider={providersById[config.provider]} busy={busyId === config.id}
              onEdit={() => { setEditor(config); setShowEditor(true) }} onTest={() => test(config.id)} onActivate={() => activate(config.id)} onDelete={() => setConfirmId(config.id)} />
          ))}
        </div>
      )}

      {showEditor && providers.length > 0 && <ConfigEditor providers={providers} initial={editor} onClose={() => { setShowEditor(false); setEditor(null) }} onSaved={saved} />}
      {confirmId && <ConfirmDialog message="This removes the encrypted API configuration from this computer. Running jobs keep their existing snapshot." onConfirm={remove} onCancel={() => setConfirmId(null)} />}
    </div>
  )
}
