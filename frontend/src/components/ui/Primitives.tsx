import { useState, type ReactNode } from 'react'

export function Card({ children, className = '' }: { children: ReactNode; className?: string }) {
  return (
    <div className={`rounded-lg border border-charcoal-600/60 bg-charcoal-800/60 p-5 shadow-xs ${className}`}>
      {children}
    </div>
  )
}

export function PageHeader({ title, description, actions }: { title: string; description?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex items-start justify-between gap-4">
      <div>
        <h1 className="text-xl font-semibold tracking-tight text-slate-100">{title}</h1>
        {description && <p className="mt-1 text-sm text-slate-400">{description}</p>}
      </div>
      {actions}
    </div>
  )
}

export function StatTile({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return (
    <Card>
      <div className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-2 text-2xl font-semibold text-slate-100">{value}</div>
      {hint && <div className="mt-1 text-xs text-slate-500">{hint}</div>}
    </Card>
  )
}

const STATUS_STYLES: Record<string, string> = {
  active: 'bg-status-good/15 text-status-good border-status-good/30',
  ready: 'bg-status-good/15 text-status-good border-status-good/30',
  ok: 'bg-status-good/15 text-status-good border-status-good/30',
  completed: 'bg-status-good/15 text-status-good border-status-good/30',
  confirmed: 'bg-status-good/15 text-status-good border-status-good/30',
  open: 'bg-accent-500/15 text-accent-400 border-accent-500/30',
  running: 'bg-accent-500/15 text-accent-400 border-accent-500/30',
  pending: 'bg-status-warning/15 text-status-warning border-status-warning/30',
  unknown: 'bg-slate-500/15 text-slate-400 border-slate-500/30',
  inactive: 'bg-slate-500/15 text-slate-400 border-slate-500/30',
  not_reviewed: 'bg-status-warning/15 text-status-warning border-status-warning/30',
  completed_with_errors: 'bg-status-serious/15 text-status-serious border-status-serious/30',
  failed: 'bg-status-critical/15 text-status-critical border-status-critical/30',
  error: 'bg-status-critical/15 text-status-critical border-status-critical/30',
  fault: 'bg-status-critical/15 text-status-critical border-status-critical/30',
  closed: 'bg-slate-500/15 text-slate-400 border-slate-500/30',
  dismissed: 'bg-slate-500/15 text-slate-400 border-slate-500/30',
  overridden: 'bg-status-serious/15 text-status-serious border-status-serious/30',
  // Phase 8: edge AI / offline-first operation
  online: 'bg-status-good/15 text-status-good border-status-good/30',
  offline: 'bg-status-warning/15 text-status-warning border-status-warning/30',
  suspended: 'bg-status-warning/15 text-status-warning border-status-warning/30',
  revoked: 'bg-status-critical/15 text-status-critical border-status-critical/30',
  queued: 'bg-status-warning/15 text-status-warning border-status-warning/30',
  syncing: 'bg-accent-500/15 text-accent-400 border-accent-500/30',
  synced: 'bg-status-good/15 text-status-good border-status-good/30',
  retryable_failure: 'bg-status-serious/15 text-status-serious border-status-serious/30',
  permanent_failure: 'bg-status-critical/15 text-status-critical border-status-critical/30',
  conflict: 'bg-status-serious/15 text-status-serious border-status-serious/30',
  quarantined: 'bg-status-critical/15 text-status-critical border-status-critical/30',
  cancelled: 'bg-slate-500/15 text-slate-400 border-slate-500/30',
  unresolved: 'bg-status-warning/15 text-status-warning border-status-warning/30',
  resolved: 'bg-status-good/15 text-status-good border-status-good/30',
  // Phase 9: enterprise edge fleet management
  maintenance: 'bg-status-warning/15 text-status-warning border-status-warning/30',
  decommissioned: 'bg-slate-500/15 text-slate-400 border-slate-500/30',
  stale: 'bg-status-warning/15 text-status-warning border-status-warning/30',
  acknowledged: 'bg-accent-500/15 text-accent-400 border-accent-500/30',
  reopened: 'bg-status-warning/15 text-status-warning border-status-warning/30',
  info: 'bg-accent-500/15 text-accent-400 border-accent-500/30',
  warning: 'bg-status-warning/15 text-status-warning border-status-warning/30',
  serious: 'bg-status-serious/15 text-status-serious border-status-serious/30',
  critical: 'bg-status-critical/15 text-status-critical border-status-critical/30',
}

export function StatusPill({ status }: { status: string }) {
  const style = STATUS_STYLES[status] ?? 'bg-slate-500/15 text-slate-400 border-slate-500/30'
  return (
    <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium ${style}`}>
      {status.replace(/_/g, ' ')}
    </span>
  )
}

// How a record entered AEGIS -- not a claim about whether its content is true.
const ORIGIN_LABELS: Record<string, { label: string; title: string }> = {
  synthetic_demo: { label: 'synthetic demo', title: 'Synthetic demonstration data -- not a real observation' },
  user_upload: { label: 'file upload', title: "Submitted as a file upload; AEGIS does not verify the file's contents" },
  external_source: { label: 'external source', title: 'Fetched from a configured external connector' },
}

export function DataOriginBadge({ origin }: { origin: string }) {
  const isSynthetic = origin === 'synthetic_demo'
  const info = ORIGIN_LABELS[origin] ?? { label: origin.replace(/_/g, ' '), title: `Data origin: ${origin}` }
  return (
    <span
      title={info.title}
      className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium ${
        isSynthetic
          ? 'border-status-warning/30 bg-status-warning/10 text-status-warning'
          : 'border-accent-500/30 bg-accent-500/10 text-accent-400'
      }`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${isSynthetic ? 'bg-status-warning' : 'bg-accent-400'}`} />
      {info.label}
    </span>
  )
}

export function Button({
  children,
  onClick,
  variant = 'primary',
  type = 'button',
  disabled,
}: {
  children: ReactNode
  onClick?: () => void
  variant?: 'primary' | 'secondary' | 'danger'
  type?: 'button' | 'submit'
  disabled?: boolean
}) {
  const styles: Record<string, string> = {
    primary: 'bg-accent-500 text-white hover:bg-accent-400 disabled:opacity-50',
    secondary: 'bg-charcoal-700 text-slate-200 hover:bg-charcoal-600 border border-charcoal-600 disabled:opacity-50',
    danger: 'bg-status-critical/90 text-white hover:bg-status-critical disabled:opacity-50',
  }
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className={`rounded-md px-3 py-1.5 text-sm font-medium transition-colors disabled:cursor-not-allowed ${styles[variant]}`}
    >
      {children}
    </button>
  )
}

export function Spinner() {
  return (
    <div className="flex items-center justify-center py-12">
      <div className="h-6 w-6 animate-spin rounded-full border-2 border-charcoal-600 border-t-accent-400" />
    </div>
  )
}

export function ErrorState({ message }: { message: string }) {
  return (
    <div className="rounded-md border border-status-critical/30 bg-status-critical/10 px-4 py-3 text-sm text-status-critical">
      {message}
    </div>
  )
}

export function EmptyState({ message }: { message: string }) {
  return <div className="rounded-md border border-dashed border-charcoal-600 px-4 py-10 text-center text-sm text-slate-500">{message}</div>
}

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-slate-400">{label}</span>
      {children}
    </label>
  )
}

export const inputClass =
  'w-full rounded-md border border-charcoal-600 bg-charcoal-900 px-3 py-1.5 text-sm text-slate-200 placeholder:text-slate-500 focus:border-accent-500 focus:outline-hidden'

export function Tabs({
  tabs,
  active,
  onChange,
}: {
  tabs: { key: string; label: string }[]
  active: string
  onChange: (key: string) => void
}) {
  return (
    <div className="mb-4 flex gap-1 border-b border-charcoal-700/60">
      {tabs.map((t) => (
        <button
          key={t.key}
          type="button"
          onClick={() => onChange(t.key)}
          className={`-mb-px border-b-2 px-3 py-2 text-sm font-medium transition-colors ${
            active === t.key ? 'border-accent-500 text-accent-400' : 'border-transparent text-slate-500 hover:text-slate-300'
          }`}
        >
          {t.label}
        </button>
      ))}
    </div>
  )
}

export function Modal({ title, children, onClose }: { title: string; children: ReactNode; onClose?: () => void }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 px-4 py-8">
      <div className="max-h-full w-full max-w-lg overflow-y-auto rounded-lg border border-charcoal-600 bg-charcoal-800 p-5 shadow-xl">
        <div className="mb-4 flex items-center justify-between gap-4">
          <h2 className="text-sm font-semibold text-slate-100">{title}</h2>
          {onClose && (
            <button type="button" onClick={onClose} aria-label="Close" className="text-slate-500 hover:text-slate-300">
              ✕
            </button>
          )}
        </div>
        {children}
      </div>
    </div>
  )
}

// A secret shown exactly once (a device API key, at registration or
// key-rotation time) -- copyable, but never persisted or re-displayed
// by this app after the dialog holding it closes.
export function OneTimeSecretField({ value }: { value: string }) {
  const [copied, setCopied] = useState(false)

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(value)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      setCopied(false)
    }
  }

  return (
    <div className="rounded-md border border-status-warning/40 bg-status-warning/10 p-3">
      <div className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-status-warning">
        Shown once -- save it now. It cannot be retrieved again.
      </div>
      <div className="flex items-center gap-2">
        <code className="flex-1 overflow-x-auto rounded-md bg-charcoal-900 px-2 py-1.5 text-xs text-slate-200">{value}</code>
        <Button variant="secondary" onClick={handleCopy}>
          {copied ? 'Copied' : 'Copy'}
        </Button>
      </div>
    </div>
  )
}
