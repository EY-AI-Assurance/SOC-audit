const STATUS = {
  processing: { label: 'Processing', badge: 'bg-blue-100 text-blue-700', icon: '⏳' },
  done:       { label: 'Done',       badge: 'bg-green-100 text-green-700', icon: '✅' },
  failed:     { label: 'Failed',     badge: 'bg-red-100 text-red-700', icon: '❌' },
}

export default function JobCard({ job, onViewDetails, onDownload, onRetry }) {
  const s = STATUS[job.status]

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-5 flex flex-col gap-3 shadow-sm">

      {/* Header row */}
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-xs text-gray-400 font-mono">#{job.id}</span>
            <span className="font-semibold text-gray-900 truncate">
              {job.reports.join(' + ')}
            </span>
          </div>
          <p className="text-xs text-gray-400 mt-0.5">
            Template: {job.template}&nbsp;&nbsp;·&nbsp;&nbsp;Sheets: {job.sheets.join(' · ')}
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
            <span>{job.currentStep}</span>
            <span>{job.progress}%</span>
          </div>
          <div className="h-1.5 bg-gray-100 rounded-full overflow-hidden">
            <div
              className="h-full bg-[#FFE600] rounded-full transition-all duration-500"
              style={{ width: `${job.progress}%` }}
            />
          </div>
        </div>
      )}

      {/* Error message */}
      {job.status === 'failed' && job.error && (
        <p className="text-xs text-red-500 bg-red-50 rounded-lg px-3 py-2">
          {job.error}
        </p>
      )}

      {/* Footer row */}
      <div className="flex items-center justify-between pt-1">
        <span className="text-xs text-gray-400">{job.date}</span>
        <div className="flex gap-2">
          {(job.status === 'processing' || job.status === 'done') && (
            <button
              onClick={() => onViewDetails(job.id)}
              className="text-xs px-3 py-1.5 rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-50 transition-colors"
            >
              View Details
            </button>
          )}
          {job.status === 'done' && (
            <button
              onClick={() => onDownload(job.id)}
              className="text-xs px-3 py-1.5 rounded-lg bg-[#FFE600] text-[#2E2E38] font-semibold hover:bg-yellow-300 transition-colors"
            >
              ↓ Download
            </button>
          )}
          {job.status === 'failed' && (
            <button
              onClick={() => onRetry(job.id)}
              className="text-xs px-3 py-1.5 rounded-lg bg-[#2E2E38] text-white font-semibold hover:bg-gray-700 transition-colors"
            >
              ↺ Retry
            </button>
          )}
        </div>
      </div>

    </div>
  )
}
