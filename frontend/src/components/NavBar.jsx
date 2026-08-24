import { useCallback, useEffect, useState } from 'react'
import { NavLink } from 'react-router-dom'
import { api } from '../api'

export default function NavBar() {
  const [active, setActive] = useState(null)

  const loadActive = useCallback(() => {
    api.listApiConfigs()
      .then(data => setActive(data.active || null))
      .catch(() => setActive(null))
  }, [])

  useEffect(() => {
    loadActive()
    window.addEventListener('api-config-changed', loadActive)
    return () => window.removeEventListener('api-config-changed', loadActive)
  }, [loadActive])

  const linkClass = ({ isActive }) =>
    `px-4 py-1.5 text-sm font-medium rounded transition-colors ${
      isActive
        ? 'bg-[#FFE600] text-[#2E2E38]'
        : 'text-gray-500 hover:text-gray-800 hover:bg-gray-100'
    }`

  return (
    <nav className="bg-white border-b border-gray-200">
      <div className="max-w-4xl mx-auto px-6 py-3 flex items-center gap-8">
        <span className="font-bold text-[#2E2E38] tracking-tight">
          EY SOC Audit
        </span>
        <div className="flex gap-1">
          <NavLink to="/jobs" className={linkClass}>Jobs</NavLink>
          <NavLink to="/reports" className={linkClass}>Reports</NavLink>
          <NavLink to="/templates" className={linkClass}>Templates</NavLink>
          <NavLink to="/apis" className={linkClass}>APIs</NavLink>
        </div>
        <NavLink
          to="/apis"
          className="ml-auto hidden sm:flex items-center gap-2 text-xs text-gray-500 hover:text-gray-800"
        >
          <span className={`h-2 w-2 rounded-full ${active ? 'bg-green-500' : 'bg-amber-400'}`} />
          <span className="max-w-48 truncate">
            {active
              ? `Active: ${active.name}${active.model ? ` / ${active.model}` : ''}`
              : 'No active API'}
          </span>
        </NavLink>
      </div>
    </nav>
  )
}
