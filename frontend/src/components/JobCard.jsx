import { useEffect, useState } from 'react'

const STATUS = {
  processing: { label: 'Processing', badge: 'bg-blue-100 text-blue-700', icon: '⏳' },
  done:       { label: 'Done',       badge: 'bg-green-100 text-green-700', icon: '✅' },
  failed:     { label: 'Failed',     badge: 'bg-red-100 text-red-700', icon: '❌' },
}

function formatDate(iso) {
  if (!iso) return ''
  return new Date(iso).toLocaleString('zh-CN', {
    month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit',
  })
}

function formatDuration(ms) {
  if (!Number.isFinite(ms) || ms < 0) return 'Estimating...'

  const totalSeconds = Math.max(0, Math.round(ms / 1000))
  if (totalSeconds < 60) return `${totalSeconds}s`

  const hours = Math.floor(totalSeconds / 3600)
  const minutes = Math.floor((totalSeconds % 3600) / 60)
  const seconds = totalSeconds % 60

  if (hours > 0) return `${hours}h ${minutes}m`
  if (minutes >= 10) return `${minutes}m`
  return `${minutes}m ${seconds}s`
}

function estimateRemaining(createdAt, progress, now) {
  if (!createdAt || progress <= 0 || progress >= 100) return null

  const started = new Date(createdAt).getTime()
  const elapsed = now - started
  if (!Number.isFinite(elapsed) || elapsed <= 0) return null

  return elapsed * ((100 - progress) / progress)
}

export default function JobCard({ job, onDownload, onDelete }) {
  const [now, setNow] = useState(Date.now())
  const s = STATUS[job.status] || STATUS.processing
  const reportNames = job.reports.map(r => r.filename.replace('.pdf', '')).join(' + ')

  useEffect(() => {
    if (job.status !== 'processing') return
    const id = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(id)
  }, [job.status])

  // For processing jobs, show progress of the current active report
  const activeReport = job.reports.find(r => r.status === 'PROCESSING')
    || job.reports.find(r => r.status === 'QUEUED')
  const overallProgress = job.reports.length
    ? Math.round(job.reports.reduce((sum, r) => sum + r.progress, 0) / job.reports.length)
    : 0
  const remainingMs = estimateRemaining(job.created_at, overallProgress, now)
  const elapsedMs = now - new Date(job.created_at).getTime()

  const doneReports = job.reports.filter(r => r.status === 'DONE')

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-5 flex flex-col gap-3 shadow-sm">

      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-xs text-gray-400 font-mono">#{job.job_id.slice(0, 8)}</span>
            <span className="font-semibold text-gray-900 truncate">{reportNames}</span>
          </div>
          <p className="text-xs text-gray-400 mt-0.5">
            Template: {job.template_name}&nbsp;&nbsp;·&nbsp;&nbsp;Sheets: {job.sheets.join(' · ')}
          </p>
        </div>
        <span className={`shrink-0 text-xs font-medium px-2.5 py-1 rounded-full ${s.badge}`}>
          {s.icon} {s.label}
        </span>
      </div>

      {/* Progress bar */}
      {job.status === 'processing' && (
        <div>
          <div className="flex justify-between text-xs text-gray-400 mb-1">
            <span>{activeReport?.current_step || 'Waiting...'}</span>
            <span>{overallProgress}%</span>
          </div>
          <div className="h-1.5 bg-gray-100 rounded-full overflow-hidden">
            <div
              className="h-full bg-[#FFE600] rounded-full transition-all duration-500"
              style={{ width: `${overallProgress}%` }}
            />
          </div>
          <div className="flex justify-between text-[11px] text-gray-400 mt-1">
            <span>Elapsed: {formatDuration(elapsedMs)}</span>
            <span>
              ETA: {remainingMs === null ? 'Estimating...' : formatDuration(remainingMs)}
            </span>
          </div>
        </div>
      )}

      {/* Done: show per-report summary + download */}
      {job.status === 'done' && doneReports.length > 0 && (
        <div className="flex flex-col gap-2">
          {doneReports.map(r => (
            <div key={r.report_id}
              className="flex items-center justify-between bg-gray-50 rounded-lg px-3 py-2">
              <div className="text-xs text-gray-600">
                <span className="font-medium">{r.summary?.system_name || r.filename}</span>
                {r.summary && (
                  <span className="text-gray-400 ml-2">
                    {r.summary.period && `${r.summary.period} · `}
                    {r.summary.has_qualified_opinion && '⚠️ Qualified · '}
                    {r.summary.exception_count > 0 && `${r.summary.exception_count} exceptions · `}
                    {r.summary.cuec_count} CUECs
                  </span>
                )}
              </div>
              <button
                onClick={() => onDownload(job.job_id, r.report_id)}
                className="shrink-0 ml-4 text-xs px-3 py-1.5 rounded-lg bg-[#FFE600] text-[#2E2E38] font-semibold hover:bg-yellow-300 transition-colors"
              >
                ↓ Download
              </button>
            </div>
          ))}
        </div>
      )}

      {/* Failed reports */}
      {job.status === 'failed' && job.reports.filter(r => r.status === 'FAILED').map(r => (
        <p key={r.report_id} className="text-xs text-red-500 bg-red-50 rounded-lg px-3 py-2">
          {r.filename}: {r.error}
        </p>
      ))}

      <div className="flex items-center justify-between pt-1">
        <span className="text-xs text-gray-400">{formatDate(job.created_at)}</span>
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
