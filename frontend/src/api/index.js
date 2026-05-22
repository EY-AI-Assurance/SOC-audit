const BASE = '/api'

async function req(method, path, body, isFile = false) {
  const opts = { method, headers: {} }
  if (body && !isFile) {
    opts.headers['Content-Type'] = 'application/json'
    opts.body = JSON.stringify(body)
  } else if (isFile) {
    opts.body = body // FormData
  }
  const res = await fetch(`${BASE}${path}`, opts)
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || 'Request failed')
  }
  if (res.status === 204) return null
  return res.json()
}

export const api = {
  // Templates
  listTemplates: ()               => req('GET',  '/templates'),
  uploadTemplate: (file)          => {
    const fd = new FormData()
    fd.append('file', file)
    return req('POST', '/templates/upload', fd, true)
  },

  // Reports
  listReports: ()                 => req('GET',  '/reports'),
  uploadReport: (file)            => {
    const fd = new FormData()
    fd.append('file', file)
    return req('POST', '/reports/upload', fd, true)
  },
  getReport: (id)                 => req('GET',  `/reports/${id}`),
  deleteReport: (id)              => req('DELETE', `/reports/${id}`),

  // Jobs
  listJobs: ()                    => req('GET',  '/jobs'),
  createJob: (templateId, reportIds, sheets) =>
    req('POST', '/jobs', { template_id: templateId, report_ids: reportIds, sheets }),
  getJob: (id)                    => req('GET',  `/jobs/${id}`),
  deleteJob: (id)                 => req('DELETE', `/jobs/${id}`),
  downloadUrl: (jobId, reportId)  => `${BASE}/jobs/${jobId}/download/${reportId}`,
}
