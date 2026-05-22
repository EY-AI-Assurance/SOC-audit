import { useEffect, useState } from 'react'
import { api } from '../api'
import ConfirmDialog from '../components/ConfirmDialog'
import JobCard from '../components/JobCard'
import NewJobModal from '../components/NewJobModal'

export default function Jobs() {
  const [jobs, setJobs]             = useState([])
  const [showModal, setModal]       = useState(false)
  const [error, setError]           = useState('')
  const [confirmId, setConfirmId]   = useState(null)

  const load = async () => {
    try {
      const data = await api.listJobs()
      setJobs(data.jobs || [])
    } catch (e) {
      setError(e.message)
    }
  }

  useEffect(() => {
    load()
  }, [])

  // Poll every 3 s while any job is processing
  useEffect(() => {
    const hasActive = jobs.some(j => j.status === 'processing')
    if (!hasActive) return
    const id = setInterval(load, 3000)
    return () => clearInterval(id)
  }, [jobs])

  const handleDownload = (jobId, reportId) => {
    window.location.href = api.downloadUrl(jobId, reportId)
  }

  const handleDeleteConfirmed = async () => {
    try {
      await api.deleteJob(confirmId)
      setJobs(prev => prev.filter(j => j.job_id !== confirmId))
    } catch (e) {
      setError(e.message)
    } finally {
      setConfirmId(null)
    }
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-xl font-bold text-[#2E2E38]">Jobs</h1>
        <button
          onClick={() => setModal(true)}
          className="px-4 py-2 bg-[#FFE600] text-[#2E2E38] text-sm font-semibold rounded-lg hover:bg-yellow-300 transition-colors"
        >
          + New Job
        </button>
      </div>

      {error && (
        <p className="text-sm text-red-500 bg-red-50 rounded-lg px-4 py-3 mb-4">{error}</p>
      )}

      {jobs.length === 0 ? (
        <div className="text-center py-20 text-gray-400">
          <p className="text-4xl mb-3">📋</p>
          <p className="text-sm">No jobs yet. Click <strong>+ New Job</strong> to get started.</p>
        </div>
      ) : (
        <div className="flex flex-col gap-4">
          {jobs.map(job => (
            <JobCard
              key={job.job_id}
              job={job}
              onDownload={handleDownload}
              onDelete={() => setConfirmId(job.job_id)}
            />
          ))}
        </div>
      )}

      {confirmId && (
        <ConfirmDialog
          message="将会在本地删除本次填写记录及输出文件，此操作不可恢复。"
          onConfirm={handleDeleteConfirmed}
          onCancel={() => setConfirmId(null)}
        />
      )}

      {showModal && (
        <NewJobModal
          onClose={() => setModal(false)}
          onCreated={() => { setModal(false); load() }}
        />
      )}
    </div>
  )
}
