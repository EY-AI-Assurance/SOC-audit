import { useState } from 'react'
import JobCard from '../components/JobCard'

const MOCK_JOBS = [
  {
    id: '003',
    reports: ['金蝶SOC1.pdf', '阿里云SOC1.pdf'],
    template: 'Form 107-A (CN).xlsx',
    sheets: ['2', '3', '6', '7', '8'],
    status: 'processing',
    progress: 60,
    currentStep: 'Extracting Sheet 6 — 金蝶SOC1.pdf',
    date: '2025-05-21 14:32',
    error: null,
  },
  {
    id: '002',
    reports: ['世纪互联SOC1.pdf'],
    template: 'Form 107-A (CN).xlsx',
    sheets: ['2', '3', '6'],
    status: 'done',
    progress: 100,
    currentStep: null,
    date: '2025-05-20 11:15',
    error: null,
  },
  {
    id: '001',
    reports: ['金蝶SOC1.pdf'],
    template: 'Form 107-A (CN).xlsx',
    sheets: ['2', '3', '6', '7', '8'],
    status: 'failed',
    progress: 45,
    currentStep: null,
    date: '2025-05-18 09:40',
    error: 'LLM extraction error on Sheet 6: JSON parse failed',
  },
]

export default function Jobs() {
  const [jobs] = useState(MOCK_JOBS)

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-xl font-bold text-[#2E2E38]">Jobs</h1>
        <button className="px-4 py-2 bg-[#FFE600] text-[#2E2E38] text-sm font-semibold rounded-lg hover:bg-yellow-300 transition-colors">
          + New Job
        </button>
      </div>

      {jobs.length === 0 ? (
        <div className="text-center py-20 text-gray-400">
          <p className="text-4xl mb-3">📋</p>
          <p className="text-sm">No jobs yet. Click <strong>+ New Job</strong> to get started.</p>
        </div>
      ) : (
        <div className="flex flex-col gap-4">
          {jobs.map(job => (
            <JobCard
              key={job.id}
              job={job}
              onViewDetails={(id) => console.log('view', id)}
              onDownload={(id) => console.log('download', id)}
              onRetry={(id) => console.log('retry', id)}
            />
          ))}
        </div>
      )}
    </div>
  )
}
