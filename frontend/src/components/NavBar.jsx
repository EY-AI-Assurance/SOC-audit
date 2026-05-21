import { NavLink } from 'react-router-dom'

export default function NavBar() {
  const linkClass = ({ isActive }) =>
    `px-4 py-1.5 text-sm font-medium rounded transition-colors ${
      isActive
        ? 'bg-[#FFE600] text-[#2E2E38]'
        : 'text-gray-500 hover:text-gray-800 hover:bg-gray-100'
    }`

  return (
    <nav className="bg-white border-b border-gray-200">
      <div className="max-w-3xl mx-auto px-6 py-3 flex items-center gap-8">
        <span className="font-bold text-[#2E2E38] tracking-tight">
          EY SOC Audit
        </span>
        <div className="flex gap-1">
          <NavLink to="/jobs" className={linkClass}>Jobs</NavLink>
          <NavLink to="/reports" className={linkClass}>Reports</NavLink>
          <NavLink to="/templates" className={linkClass}>Templates</NavLink>
        </div>
      </div>
    </nav>
  )
}
