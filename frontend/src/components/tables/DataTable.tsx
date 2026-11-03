import type { ReactNode } from 'react'
import { Button } from '../ui/Primitives'

export interface Column<T> {
  header: string
  render: (row: T) => ReactNode
  className?: string
}

export function DataTable<T extends { id: string }>({
  columns,
  rows,
  onRowClick,
}: {
  columns: Column<T>[]
  rows: T[]
  onRowClick?: (row: T) => void
}) {
  return (
    <div className="overflow-x-auto rounded-lg border border-charcoal-600/60">
      <table className="w-full text-left text-sm">
        <thead>
          <tr className="border-b border-charcoal-600/60 bg-charcoal-800/80 text-xs uppercase tracking-wide text-slate-500">
            {columns.map((col) => (
              <th key={col.header} className="px-4 py-2.5 font-medium">
                {col.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr
              key={row.id}
              onClick={() => onRowClick?.(row)}
              className={`border-b border-charcoal-700/60 last:border-0 ${
                onRowClick ? 'cursor-pointer hover:bg-charcoal-700/40' : ''
              }`}
            >
              {columns.map((col) => (
                <td key={col.header} className={`px-4 py-2.5 text-slate-300 ${col.className ?? ''}`}>
                  {col.render(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function Pagination({
  page,
  pageSize,
  total,
  onPageChange,
}: {
  page: number
  pageSize: number
  total: number
  onPageChange: (page: number) => void
}) {
  const totalPages = Math.max(1, Math.ceil(total / pageSize))
  return (
    <div className="mt-3 flex items-center justify-between text-sm text-slate-400">
      <span>
        {total === 0 ? 'No results' : `Page ${page} of ${totalPages} -- ${total} total`}
      </span>
      <div className="flex gap-2">
        <Button variant="secondary" disabled={page <= 1} onClick={() => onPageChange(page - 1)}>
          Previous
        </Button>
        <Button variant="secondary" disabled={page >= totalPages} onClick={() => onPageChange(page + 1)}>
          Next
        </Button>
      </div>
    </div>
  )
}
