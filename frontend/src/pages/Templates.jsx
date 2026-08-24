import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api'
import ConfirmDialog from '../components/ConfirmDialog'

function formatDate(iso) {
  if (!iso) return ''
  return new Date(iso).toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function TemplateCard({ template, onDelete }) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-5 flex flex-col gap-3 shadow-sm">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-xs text-gray-400 font-mono">#{template.template_id.slice(0, 8)}</span>
            <span className="font-semibold text-gray-900 truncate">{template.name}</span>
          </div>
          <p className="text-xs text-gray-400 mt-0.5">
            Uploaded: {formatDate(template.uploaded_at) || 'Unknown'}
          </p>
        </div>
        <span className="shrink-0 text-xs font-medium px-2.5 py-1 rounded-full bg-green-100 text-green-700">
          Uploaded
        </span>
      </div>

      <div className="flex items-center justify-between pt-1">
        <span className="text-xs text-gray-400">
          Available for new jobs.
        </span>
        <button
          onClick={onDelete}
          className="text-gray-300 hover:text-red-400 transition-colors p-1"
          title="删除"
        >
          🗑
        </button>
      </div>
    </div>
  )
}

export default function Templates() {
  const [templates, setTemplates] = useState([])
  const [error, setError] = useState('')
  const [uploading, setUploading] = useState(false)
  const [confirmId, setConfirmId] = useState(null)
  const inputRef = useRef()

  const load = useCallback(async () => {
    try {
      const data = await api.listTemplates()
      setTemplates(data.templates || [])
    } catch (e) {
      setError(e.message)
    }
  }, [])

  useEffect(() => {
    const timer = window.setTimeout(load, 0)
    return () => window.clearTimeout(timer)
  }, [load])

  const handleUpload = async (event) => {
    const files = Array.from(event.target.files || [])
    if (files.length === 0) return

    setUploading(true)
    setError('')
    try {
      for (const file of files) {
        await api.uploadTemplate(file)
      }
      await load()
    } catch (e) {
      setError(e.message)
    } finally {
      setUploading(false)
      event.target.value = ''
    }
  }

  const handleDeleteConfirmed = async () => {
    try {
      await api.deleteTemplate(confirmId)
      setTemplates(prev => prev.filter(template => template.template_id !== confirmId))
    } catch (e) {
      setError(e.message)
    } finally {
      setConfirmId(null)
    }
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-xl font-bold text-[#2E2E38]">Templates</h1>
        <button
          onClick={() => inputRef.current.click()}
          disabled={uploading}
          className="px-4 py-2 bg-[#FFE600] text-[#2E2E38] text-sm font-semibold rounded-lg hover:bg-yellow-300 transition-colors disabled:opacity-50"
        >
          {uploading ? 'Uploading...' : '+ Upload Templates'}
        </button>
        <input
          ref={inputRef}
          type="file"
          accept=".xlsx"
          multiple
          className="hidden"
          onChange={handleUpload}
        />
      </div>

      {error && (
        <p className="text-sm text-red-500 bg-red-50 rounded-lg px-4 py-3 mb-4">{error}</p>
      )}

      {templates.length === 0 ? (
        <div className="text-center py-20 text-gray-400">
          <p className="text-4xl mb-3">📄</p>
          <p className="text-sm">No templates yet. Click <strong>+ Upload Templates</strong> to add Form 107-A templates.</p>
        </div>
      ) : (
        <div className="flex flex-col gap-4">
          {templates.map(template => (
            <TemplateCard
              key={template.template_id}
              template={template}
              onDelete={() => setConfirmId(template.template_id)}
            />
          ))}
        </div>
      )}

      {confirmId && (
        <ConfirmDialog
          message="将会在本地删除该模板文件和模板记录，此操作不可恢复。"
          onConfirm={handleDeleteConfirmed}
          onCancel={() => setConfirmId(null)}
        />
      )}
    </div>
  )
}
