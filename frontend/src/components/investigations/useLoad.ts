import { ApiError } from '../../api/client'
import { useCallback, useEffect, useState } from 'react'

/** Loads data from a real API call; exposes loading / error (for permission-denied vs other) / reload. */
export function useLoad<T>(fn: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [loading, setLoading] = useState(true)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const run = useCallback(fn, deps)
  const reload = useCallback(() => {
    setLoading(true)
    run()
      .then((d) => {
        setData(d)
        setError(null)
      })
      .catch((e) => setError(e))
      .finally(() => setLoading(false))
  }, [run])
  useEffect(reload, [reload])
  return { data, error, loading, reload }
}

export function fmtTime(iso: string | null | undefined): string {
  if (!iso) return 'Unknown (not recorded)'
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? 'Invalid timestamp' : `${d.toISOString().replace('T', ' ').replace(/\.\d+Z$/, '')} UTC`
}

export function errorText(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return err.status === 409 ? `${err.message}` : err.message
  return err instanceof Error ? err.message : fallback
}

export const RESULT_LABEL: Record<string, string> = {
  match: 'Match -- stored bytes hash to the recorded value',
  mismatch: 'MISMATCH -- stored bytes differ from the recorded value',
  original_unavailable: 'Original unavailable -- stored file could not be read',
  no_recorded_hash: 'No recorded hash -- nothing to compare against',
  not_file_backed: 'Not file-backed -- this is a reference; nothing to hash',
}
