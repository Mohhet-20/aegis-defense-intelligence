import type { ParamDoc } from '../../types/scenario'

export const SIM_NOTICE =
  'SIMULATED: everything on this page comes from a simulation on synthetic data under stated assumptions. It is hypothetical, is not an observation of the real world, and is not evidence. It has not changed any assessment.'

export function fmt(v: unknown, digits = 4): string {
  if (v === null || v === undefined) return 'undefined'
  if (typeof v === 'number') return Number.isInteger(v) ? String(v) : v.toFixed(digits).replace(/0+$/, '').replace(/\.$/, '')
  if (typeof v === 'boolean') return v ? 'true' : 'false'
  return String(v)
}

export function rangeText(p: ParamDoc): string {
  if (p.type === 'choice') return `one of: ${(p.choices ?? []).join(', ')}`
  if (p.type === 'bool') return 'true / false'
  return `${p.min ?? '-'} to ${p.max ?? '-'}${p.unit ? ` ${p.unit}` : ''}`
}

export function downloadText(filename: string, text: string, type: string) {
  const url = URL.createObjectURL(new Blob([text], { type }))
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}
