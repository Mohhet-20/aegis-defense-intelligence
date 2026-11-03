export const fmtDate = (s: string | null | undefined) => (s ? new Date(s).toLocaleString() : '—')
export const pct = (v: number | null | undefined) => (v == null ? 'n/a' : `${(v * 100).toFixed(1)}%`)
export const shortHash = (h: string | null | undefined) => (h ? h.slice(0, 12) : '—')

/** Roles that may perform an action. This only decides which buttons to show; the server enforces every permission. */
export const canReview = (role?: string) => role === 'analyst' || role === 'administrator'
export const canApprove = (role?: string) => role === 'administrator'
