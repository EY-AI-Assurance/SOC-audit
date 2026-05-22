import { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import ConfirmDialog from '../components/ConfirmDialog'

const STATUS = {
  parsing: { label: 'Parsing', badge: 'bg-blue-100 text-blue-700', icon: '⏳' },
  ready:   { label: 'Ready',   badge: 'bg-green-100 text-green-700', icon: '✅' },
  failed:  { label: 'Failed',  badge: 'bg-red-100 text-red-700', icon: '❌' },
}

function formatDate(iso) {
  if (!iso) return ''
  return new Date(iso).toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function ReportCard({ report, onDelete }) {
  const status = STATUS[report.status] || STATUS.parsing

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-5 flex flex-col gap-3 shadow-sm">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-xs text-gray-400 font-mono">#{report.report_id.slice(0, 8)}</span>
            <span className="font-semibold text-gray-900 truncate">{report.filename}</span>
          </div>
          <p className="text-xs text-gray-400 mt-0.5">
            Uploaded: {formatDate(report.uploaded_at) || 'Unknown'}
            {report.system_name && (
              <span>&nbsp;&nbsp;·&nbsp;&nbsp;System: {report.system_name}</span>
            )}
          </p>
        </div>
        <span className={`shrink-0 text-xs font-medium px-2.5 py-1 rounded-full ${status.badge}`}>
          {status.icon} {status.label}
        </span>
      </div>

      {report.status === 'parsing' && (
        <div>
          <div className="flex justify-between text-xs text-gray-400 mb-1">
            <span>Parsing PDF...</span>
            <span>Processing</span>
          </div>
          <div className="h-1.5 bg-gray-100 rounded-full overflow-hidden">
            <div className="h-full bg-[#FFE600] rounded-full w-1/2 animate-pulse" />
          </div>
        </div>
      )}

      {report.status === 'failed' && (
        <p className="text-xs text-red-500 bg-red-50 rounded-lg px-3 py-2">
          Parse failed. Delete and upload again after checking the PDF.
        </p>
      )}

      <div className="flex items-center justify-between pt-1">
        <span className="text-xs text-gray-400">
          {report.status === 'ready' ? 'Parsed report is available for new jobs.' : ''}
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

export default function Reports() {
  const [reports, setReports] = useState([])
  const [error, setError] = useState('')
  const [uploading, setUploading] = useState(false)
  const [confirmId, setConfirmId] = useState(null)
  const inputRef = useRef()

  const load = async () => {
    try {
      const data = await api.listReports()
      setReports(data.reports || [])
    } catch (e) {
      setError(e.message)
    }
  }

  useEffect(() => {
    load()
  }, [])

  useEffect(() => {
    const hasParsing = reports.some(report => report.status === 'parsing')
    if (!hasParsing) return
    const id = setInterval(load, 3000)
    return () => clearInterval(id)
  }, [reports])

  const handleUpload = async (event) => {
    const files = Array.from(event.target.files || [])
    if (files.length === 0) return

    setUploading(true)
    setError('')
    try {
      for (const file of files) {
        await api.uploadReport(file)
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
      await api.deleteReport(confirmId)
      setReports(prev => prev.filter(report => report.report_id !== confirmId))
    } catch (e) {
      setError(e.message)
    } finally {
      setConfirmId(null)
    }
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-xl font-bold text-[#2E2E38]">Reports</h1>
        <button
          onClick={() => inputRef.current.click()}
          disabled={uploading}
          className="px-4 py-2 bg-[#FFE600] text-[#2E2E38] text-sm font-semibold rounded-lg hover:bg-yellow-300 transition-colors disabled:opacity-50"
        >
          {uploading ? 'Uploading...' : '+ Upload Reports'}
        </button>
        <input
          ref={inputRef}
          type="file"
          accept=".pdf"
          multiple
          className="hidden"
          onChange={handleUpload}
        />
      </div>

      {error && (
        <p className="text-sm text-red-500 bg-red-50 rounded-lg px-4 py-3 mb-4">{error}</p>
      )}

      {reports.length === 0 ? (
        <div className="text-center py-20 text-gray-400">
          <p className="text-4xl mb-3">📂</p>
          <p className="text-sm">No reports yet. Click <strong>+ Upload Reports</strong> to add SOC reports.</p>
        </div>
      ) : (
        <div className="flex flex-col gap-4">
          {reports.map(report => (
            <ReportCard
              key={report.report_id}
              report={report}
              onDelete={() => setConfirmId(report.report_id)}
            />
          ))}
        </div>
      )}

      {confirmId && (
        <ConfirmDialog
          message="将会在本地删除该 SOC report 的上传文件和解析记录，此操作不可恢复。"
          onConfirm={handleDeleteConfirmed}
          onCancel={() => setConfirmId(null)}
        />
      )}
    </div>
  )
}
