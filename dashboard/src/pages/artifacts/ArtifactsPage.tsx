import { useRef, useState } from 'react'
import { Download, FileArchive, RefreshCw, Trash2, Upload } from 'lucide-react'
import { formatBytes } from '@/api/artifacts'
import { EmptyState } from '@/components/shared/EmptyState'
import { Pagination } from '@/components/shared/Pagination'
import { useArtifacts, useDeleteArtifact, useUploadArtifact } from '@/hooks/useArtifacts'

const PAGE_SIZE = 25

export function ArtifactsPage() {
  const fileRef = useRef<HTMLInputElement | null>(null)
  const [page, setPage] = useState(0)
  const [namespace, setNamespace] = useState('shared')
  const artifacts = useArtifacts({ limit: PAGE_SIZE, offset: page * PAGE_SIZE })
  const uploader = useUploadArtifact()
  const deleter = useDeleteArtifact()

  async function upload(file: File | undefined) {
    if (!file || !namespace.trim()) return
    await uploader.mutateAsync({ file, namespace: namespace.trim() })
    if (fileRef.current) fileRef.current.value = ''
  }

  const items = artifacts.data?.items ?? []
  const total = artifacts.data?.total ?? 0

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-3 border-b border-border pb-4 sm:flex-row sm:items-end sm:justify-between">
        <label className="min-w-0 flex-1 text-xs font-medium text-content-secondary">
          Upload namespace
          <input
            value={namespace}
            onChange={(event) => setNamespace(event.target.value)}
            className="mt-1 w-full max-w-md rounded-md border border-border bg-white px-3 py-2 text-sm text-content-primary outline-none focus:border-brand-primary"
          />
        </label>
        <div className="flex gap-2">
          <button
            type="button"
            title="Refresh artifacts"
            aria-label="Refresh artifacts"
            onClick={() => artifacts.refetch()}
            className="rounded-md border border-border bg-white p-2 text-content-secondary hover:bg-surface-secondary"
          >
            <RefreshCw size={16} />
          </button>
          <button
            type="button"
            onClick={() => fileRef.current?.click()}
            disabled={!namespace.trim() || uploader.isPending}
            className="inline-flex items-center gap-2 rounded-md bg-brand-primary px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
          >
            <Upload size={16} /> Upload
          </button>
          <input ref={fileRef} type="file" className="hidden" onChange={(event) => upload(event.target.files?.[0])} />
        </div>
      </div>

      {uploader.isError && <p className="text-sm text-status-danger">Upload failed.</p>}
      {artifacts.isLoading ? (
        <div className="py-16 text-center text-sm text-content-secondary">Loading artifacts...</div>
      ) : items.length === 0 ? (
        <EmptyState icon={FileArchive} title="No artifacts yet" description="Upload a file into a namespace to keep it beside its memories." />
      ) : (
        <div className="overflow-hidden rounded-lg border border-border bg-white">
          <div className="overflow-x-auto">
            <table className="w-full table-fixed text-left text-sm">
              <thead className="border-b border-border bg-surface-secondary text-xs text-content-secondary">
                <tr>
                  <th className="w-[38%] px-4 py-2 font-medium">File</th>
                  <th className="w-[24%] px-4 py-2 font-medium">Namespace</th>
                  <th className="w-[14%] px-4 py-2 font-medium">Type</th>
                  <th className="w-[14%] px-4 py-2 font-medium">Size</th>
                  <th className="w-[10%] px-4 py-2 text-right font-medium">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {items.map((artifact) => (
                  <tr key={artifact.artifact_id}>
                    <td className="truncate px-4 py-3 font-medium text-content-primary">{artifact.filename || artifact.artifact_id}</td>
                    <td className="truncate px-4 py-3 font-mono text-xs text-content-secondary">{artifact.namespace || 'shared'}</td>
                    <td className="px-4 py-3 text-content-secondary">{artifact.artifact_type}</td>
                    <td className="px-4 py-3 text-content-secondary">{formatBytes(artifact.size_bytes)}</td>
                    <td className="px-4 py-3">
                      <div className="flex justify-end gap-1">
                        {artifact.content_url && (
                          <a href={artifact.content_url} title="Open artifact" aria-label="Open artifact" className="rounded p-1.5 text-content-secondary hover:bg-surface-secondary">
                            <Download size={15} />
                          </a>
                        )}
                        <button
                          type="button"
                          title="Delete artifact"
                          aria-label="Delete artifact"
                          onClick={() => deleter.mutate(artifact.artifact_id)}
                          className="rounded p-1.5 text-content-secondary hover:bg-red-50 hover:text-status-danger"
                        >
                          <Trash2 size={15} />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Pagination
            page={page}
            pageCount={Math.max(1, Math.ceil(total / PAGE_SIZE))}
            pageSize={PAGE_SIZE}
            total={total}
            label="artifacts"
            onPageChange={setPage}
            onPageSizeChange={() => undefined}
            sizeOptions={[PAGE_SIZE]}
          />
        </div>
      )}
    </div>
  )
}
