import { useEffect, useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import type { MediaAsset, Page } from '../../types/api'
import { useAuth } from '../../context/auth'
import { DataTable, Pagination } from '../../components/tables/DataTable'
import { Button, Card, EmptyState, ErrorState, Field, PageHeader, Spinner, StatusPill } from '../../components/ui/Primitives'

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / (1024 * 1024)).toFixed(1)} MB`
}

export function MediaLibraryPage() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const [page, setPage] = useState(1)
  const [data, setData] = useState<Page<MediaAsset> | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [file, setFile] = useState<File | null>(null)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const [uploading, setUploading] = useState(false)

  const canUpload = user?.role === 'administrator' || user?.role === 'analyst'

  function load() {
    api.media
      .list(page, 20)
      .then((d) => {
        setData(d)
        setError(null)
      })
      .catch((e) => setError(e.message))
  }

  useEffect(load, [page])

  async function handleUpload(e: FormEvent) {
    e.preventDefault()
    if (!file) return
    setUploadError(null)
    setUploading(true)
    try {
      await api.media.upload(file)
      setFile(null)
      load()
    } catch (err) {
      setUploadError(err instanceof ApiError ? err.message : 'Upload failed.')
    } finally {
      setUploading(false)
    }
  }

  return (
    <div>
      <PageHeader
        title="Media Library"
        description="Every upload is signature-sniffed from its real bytes, size/dimension/duration-checked, content-hashed, and stored outside any public directory. See docs/security/MEDIA_UPLOAD_SECURITY.md."
      />

      {canUpload && (
        <Card className="mb-5 max-w-lg">
          <form onSubmit={handleUpload} className="space-y-3">
            <Field label="Image (.png/.jpg) or video (.mp4)">
              <input
                type="file"
                accept="image/png,image/jpeg,video/mp4"
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                className="w-full text-sm text-slate-300"
              />
            </Field>
            {uploadError && <ErrorState message={uploadError} />}
            <Button type="submit" disabled={uploading || !file}>
              {uploading ? 'Uploading…' : 'Upload'}
            </Button>
          </form>
        </Card>
      )}

      {error && <ErrorState message={error} />}
      {!data && !error && <Spinner />}
      {data && data.items.length === 0 && <EmptyState message="No media uploaded yet." />}
      {data && data.items.length > 0 && (
        <>
          <DataTable
            rows={data.items}
            onRowClick={(row) => navigate(`/cv/image-detection?media=${row.id}`)}
            columns={[
              { header: 'Filename', render: (r) => r.declared_filename },
              { header: 'Type', render: (r) => <StatusPill status={r.media_type} /> },
              { header: 'MIME', render: (r) => r.detected_mime_type },
              { header: 'Size', render: (r) => formatBytes(r.byte_size) },
              { header: 'Dimensions', render: (r) => (r.width_px && r.height_px ? `${r.width_px}×${r.height_px}` : '--') },
              { header: 'Duration', render: (r) => (r.duration_seconds != null ? `${r.duration_seconds.toFixed(1)}s` : '--') },
              { header: 'Uploaded', render: (r) => new Date(r.created_at).toLocaleString() },
            ]}
          />
          <Pagination page={data.page} pageSize={data.page_size} total={data.total} onPageChange={setPage} />
        </>
      )}
    </div>
  )
}
