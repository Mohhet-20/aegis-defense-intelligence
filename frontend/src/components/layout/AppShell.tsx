import { useEffect, useState, type ReactNode } from 'react'
import { NavLink, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../../context/auth'
import { api } from '../../api/client'
import { groupForPath, visibleGroups } from './navigation'

const linkClass = ({ isActive }: { isActive: boolean }) =>
  `block rounded-md px-3 py-1.5 text-sm transition-colors focus:outline-hidden focus-visible:ring-2 focus-visible:ring-accent-500 ${
    isActive ? 'bg-accent-500/15 font-medium text-accent-400' : 'text-slate-400 hover:bg-charcoal-700/60 hover:text-slate-200'
  }`

export function AppShell({ children }: { children: ReactNode }) {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const [dbOk, setDbOk] = useState<boolean | null>(null)
  const [menuOpen, setMenuOpen] = useState(false)
  const activeGroup = groupForPath(pathname)
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set(activeGroup ? [activeGroup] : []))
  const groups = visibleGroups(user?.role)

  useEffect(() => {
    let cancelled = false
    api.health
      .ready()
      .then((r) => !cancelled && setDbOk(r.checks.database === 'ok'))
      .catch(() => !cancelled && setDbOk(false))
    return () => {
      cancelled = true
    }
  }, [])

  // Follow navigation: open the section of the current page, close the phone menu.
  useEffect(() => {
    setMenuOpen(false)
    if (activeGroup) setExpanded((prev) => (prev.has(activeGroup) ? prev : new Set(prev).add(activeGroup)))
  }, [pathname, activeGroup])

  const toggle = (title: string) =>
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(title)) next.delete(title)
      else next.add(title)
      return next
    })

  return (
    <div className="flex min-h-screen bg-navy-950">
      {menuOpen && <div className="fixed inset-0 z-30 bg-black/60 md:hidden" onClick={() => setMenuOpen(false)} aria-hidden="true" />}
      <aside
        id="app-sidebar"
        className={`fixed inset-y-0 left-0 z-40 flex w-64 flex-col border-r border-charcoal-700/60 bg-navy-900 transition-transform md:sticky md:top-0 md:h-screen md:translate-x-0 ${
          menuOpen ? 'translate-x-0' : '-translate-x-full'
        }`}
      >
        <div className="flex items-center gap-2 border-b border-charcoal-700/60 px-5 py-4">
          <div className="flex h-7 w-7 items-center justify-center rounded-sm bg-accent-500 text-xs font-bold text-white">AE</div>
          <div>
            <div className="text-sm font-semibold text-slate-100">AEGIS</div>
            <div className="text-[10px] uppercase tracking-wide text-slate-500">Defense intelligence &amp; situational awareness</div>
          </div>
        </div>
        <nav className="flex-1 overflow-y-auto px-3 py-3" aria-label="Main">
          <NavLink to="/" end className={linkClass}>
            Overview
          </NavLink>
          {groups.map((group) => {
            const open = expanded.has(group.title)
            const id = `nav-${group.title.replace(/\W+/g, '-').toLowerCase()}`
            return (
              <div key={group.title} className="mt-2">
                <button
                  type="button"
                  onClick={() => toggle(group.title)}
                  aria-expanded={open}
                  aria-controls={id}
                  className={`flex w-full items-center justify-between rounded-md px-3 py-1.5 text-left text-[11px] font-semibold uppercase tracking-wide hover:bg-charcoal-700/40 focus:outline-hidden focus-visible:ring-2 focus-visible:ring-accent-500 ${
                    group.title === activeGroup ? 'text-slate-200' : 'text-slate-500'
                  }`}
                >
                  {group.title}
                  <span aria-hidden="true" className={`transition-transform ${open ? 'rotate-90' : ''}`}>
                    ›
                  </span>
                </button>
                {open && (
                  <div id={id} className="mt-0.5 space-y-0.5 border-l border-charcoal-700/60 pl-2 ml-3">
                    {group.items.map((item) => (
                      <NavLink key={item.to} to={item.to} end className={linkClass}>
                        {item.label}
                      </NavLink>
                    ))}
                  </div>
                )}
              </div>
            )
          })}
        </nav>
        <div className="border-t border-charcoal-700/60 px-5 py-3 text-[11px] text-slate-500" role="status">
          <span className={`mr-1.5 inline-block h-1.5 w-1.5 rounded-full ${dbOk ? 'bg-status-good' : dbOk === false ? 'bg-status-critical' : 'bg-slate-500'}`} />
          Database {dbOk === null ? 'checking…' : dbOk ? 'connected' : 'unreachable'}
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center justify-between gap-3 border-b border-charcoal-700/60 bg-navy-900/60 px-4 py-3 md:px-6">
          <div className="flex min-w-0 items-center gap-3">
            <button
              type="button"
              onClick={() => setMenuOpen(true)}
              className="rounded-md border border-charcoal-600 px-2.5 py-1.5 text-sm text-slate-300 hover:bg-charcoal-700/60 md:hidden"
              aria-label="Open navigation"
              aria-controls="app-sidebar"
              aria-expanded={menuOpen}
            >
              ☰
            </button>
            <div className="truncate text-xs font-medium uppercase tracking-wide text-status-warning">
              Decision-support only -- no autonomous targeting or weapon control
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-3">
            {user && (
              <div className="hidden text-right sm:block">
                <div className="text-sm font-medium text-slate-200">{user.display_name}</div>
                <div className="text-xs capitalize text-slate-500">{user.role}</div>
              </div>
            )}
            <button
              onClick={() => {
                logout()
                navigate('/login')
              }}
              className="rounded-md border border-charcoal-600 px-3 py-1.5 text-xs font-medium text-slate-300 hover:bg-charcoal-700/60"
            >
              Sign out
            </button>
          </div>
        </header>
        <main className="flex-1 overflow-y-auto px-4 py-6 md:px-6">{children}</main>
      </div>
    </div>
  )
}
