import { useEffect, useRef, useState } from 'react'
import { api } from '../api'

const SHEET_LABELS = {
  2: 'Sheet 2 — Report Metadata',
  3: 'Sheet 3 — Opinion & Exceptions',
  6: 'Sheet 6 — ITGC Controls',
  7: 'Sheet 7 — Subservice Organizations',
  8: 'Sheet 8 — CUECs',
  9: 'Sheet 9 — CSOCs',
}

export default function NewJobModal({ onClose, onCreated }) {
  const [templates, setTemplates]       = useState([])
  const [reports, setReports]           = useState([])
  const [selectedTemplate, setTemplate] = useState('')
  const [selectedReports, setReports_]  = useState([])
  const [selectedSheets, setSheets]     = useState([])
  const [uploading, setUploading]       = useState(false)
  const [submitting, setSubmitting]     = useState(false)
  const [error, setError]               = useState('')
  const reportInputRef                  = useRef()
  const templateInputRef                = useRef()

  useEffect(() => {
    Promise.all([api.listTemplates(), api.listReports()]).then(([t, r]) => {
      setTemplates(t.templates || [])
      const ready = (r.reports || []).filter(rep => rep.status === 'ready')
      setReports(ready)
      if (t.templates?.length > 0) {
        const firstTemplate = t.templates[0]
        setTemplate(firstTemplate.template_id)
        setSheets(firstTemplate.available_sheets || [])
      }
    }).catch(e => setError(e.message))
  }, [])

  const selectedTemplateMeta = templates.find(t => t.template_id === selectedTemplate)
  const availableSheets = selectedTemplateMeta?.available_sheets || []

  const handleSelectTemplate = (templateId) => {
    const template = templates.find(item => item.template_id === templateId)
    setTemplate(templateId)
    setSheets(template?.available_sheets || [])
  }

  const toggleReport = (id) =>
    setReports_(prev => prev.includes(id) ? prev.filter(r => r !== id) : [...prev, id])

  const toggleSheet = (s) =>
    setSheets(prev => prev.includes(s) ? prev.filter(x => x !== s) : [...prev, s])

  const allSheetsSelected = availableSheets.length > 0
    && availableSheets.every(sheet => selectedSheets.includes(sheet))
  const jobCount = selectedReports.length

  const handleUploadReport = async (e) => {
    const file = e.target.files?.[0]
    if (!file) return
    setUploading(true)
    setError('')
    try {
      const res = await api.uploadReport(file)
      // Poll until parsed
      const poll = setInterval(async () => {
        const status = await api.getReport(res.report_id)
        if (status.status === 'ready') {
          clearInterval(poll)
          setUploading(false)
          setReports(prev => [{
            report_id: res.report_id,
            filename: file.name,
            status: 'ready',
          }, ...prev])
          setReports_(prev => [...prev, res.report_id])
        } else if (status.status === 'failed') {
          clearInterval(poll)
          setUploading(false)
          setError(`Failed to parse ${file.name}: ${status.error}`)
        }
      }, 2000)
    } catch (e) {
      setUploading(false)
      setError(e.message)
    }
  }

  const handleUploadTemplate = async (e) => {
    const file = e.target.files?.[0]
    if (!file) return
    try {
      const res = await api.uploadTemplate(file)
      setTemplates(prev => [...prev, res])
      setTemplate(res.template_id)
      setSheets(res.available_sheets || [])
    } catch (e) {
      setError(e.message)
    }
  }

  const handleSubmit = async () => {
    if (!selectedTemplate) return setError('Please select a template')
    if (selectedReports.length === 0) return setError('Please select at least one report')
    if (selectedSheets.length === 0) return setError('Please select at least one sheet')
    setSubmitting(true)
    setError('')
    try {
      const res = await api.createJob(selectedTemplate, selectedReports, selectedSheets)
      onCreated(res.jobs || [])
    } catch (e) {
      setError(e.message)
      setSubmitting(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-2xl w-full max-w-lg shadow-xl flex flex-col max-h-[90vh]">

        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100">
          <h2 className="font-bold text-[#2E2E38] text-lg">New Job</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl leading-none">×</button>
        </div>

        <div className="overflow-y-auto px-6 py-4 flex flex-col gap-5">

          {/* Template */}
          <div>
            <label className="block text-sm font-semibold text-gray-700 mb-2">Template</label>
            {templates.length > 0 ? (
              <select
                value={selectedTemplate}
                onChange={e => handleSelectTemplate(e.target.value)}
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#FFE600]"
              >
                {templates.map(t => (
                  <option key={t.template_id} value={t.template_id}>{t.name}</option>
                ))}
              </select>
            ) : (
              <p className="text-sm text-gray-400 mb-2">No templates yet.</p>
            )}
            <input ref={templateInputRef} type="file" accept=".xlsx" className="hidden" onChange={handleUploadTemplate} />
            <button
              onClick={() => templateInputRef.current.click()}
              className="mt-2 text-xs text-blue-500 hover:underline"
            >+ Upload new template</button>
          </div>

          {/* Reports */}
          <div>
            <label className="block text-sm font-semibold text-gray-700 mb-2">SOC Reports</label>
            {reports.length === 0 && !uploading && (
              <p className="text-sm text-gray-400 mb-2">No parsed reports yet.</p>
            )}
            <div className="flex flex-col gap-1 max-h-40 overflow-y-auto">
              {reports.map(r => (
                <label key={r.report_id} className="flex items-center gap-2 cursor-pointer hover:bg-gray-50 rounded px-2 py-1">
                  <input
                    type="checkbox"
                    checked={selectedReports.includes(r.report_id)}
                    onChange={() => toggleReport(r.report_id)}
                    className="accent-[#2E2E38]"
                  />
                  <span className="text-sm text-gray-700">{r.filename}</span>
                  <span className="ml-auto text-xs text-green-500">Ready</span>
                </label>
              ))}
            </div>
            {uploading && (
              <p className="text-xs text-blue-500 mt-2 animate-pulse">⏳ Parsing uploaded PDF...</p>
            )}
            <input ref={reportInputRef} type="file" accept=".pdf" className="hidden" onChange={handleUploadReport} />
            <button
              onClick={() => reportInputRef.current.click()}
              disabled={uploading}
              className="mt-2 text-xs text-blue-500 hover:underline disabled:opacity-50"
            >+ Upload new report</button>
          </div>

          {/* Sheets */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <label className="text-sm font-semibold text-gray-700">Sheets to Fill</label>
              <button
                onClick={() => setSheets(allSheetsSelected ? [] : availableSheets)}
                className="text-xs text-blue-500 hover:underline"
              >{allSheetsSelected ? 'Deselect All' : 'Select All'}</button>
            </div>
            <div className="flex flex-col gap-1">
              {availableSheets.map(s => (
                <label key={s} className="flex items-center gap-2 cursor-pointer hover:bg-gray-50 rounded px-2 py-1">
                  <input
                    type="checkbox"
                    checked={selectedSheets.includes(s)}
                    onChange={() => toggleSheet(s)}
                    className="accent-[#2E2E38]"
                  />
                  <span className="text-sm text-gray-700">{SHEET_LABELS[s]}</span>
                </label>
              ))}
              {selectedTemplate && availableSheets.length === 0 && (
                <p className="text-xs text-amber-700 bg-amber-50 rounded-lg px-3 py-2">
                  This template does not contain any supported sheets. Supported sheets are 2, 3, 6, 7, 8, and 9.
                </p>
              )}
            </div>
          </div>

          {error && <p className="text-xs text-red-500 bg-red-50 rounded-lg px-3 py-2">{error}</p>}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between px-6 py-4 border-t border-gray-100">
          <button onClick={onClose} className="text-sm text-gray-500 hover:text-gray-700">Cancel</button>
          <button
            onClick={handleSubmit}
            disabled={submitting || !selectedTemplate || availableSheets.length === 0}
            className="px-5 py-2 bg-[#FFE600] text-[#2E2E38] text-sm font-semibold rounded-lg hover:bg-yellow-300 transition-colors disabled:opacity-50"
          >
            {submitting ? 'Creating...' : `Run ${jobCount > 1 ? `${jobCount} Jobs` : 'Job'} →`}
          </button>
        </div>

      </div>
    </div>
  )
}
