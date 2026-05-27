/**
 * Kemory dashboard — Namespace Files tab (project files — v3.35.0).
 *
 * Renders a file grid for all artifacts in a namespace (namespace-level,
 * memory-attached, and chat-attached — they all share the same namespace
 * column after migration 016).
 *
 * Features:
 *   - File cards showing icon, name, size, type badge, and date
 *   - "Upload file" button opens a native <input type="file">
 *   - Delete with inline confirmation
 *   - Image preview inline (uses content_url signed redirect)
 */
import { useRef, useState } from 'react'
import {
  File,
  FileAudio,
  FileCode,
  FileText,
  FileVideo,
  Image,
  RefreshCw,
  Trash2,
  Upload,
  X,
} from 'lucide-react'
import { useQueryClient } from '@tanstack/react-query'
import { formatBytes } from '@/api/artifacts'
import type { ArtifactResponse } from '@/api/chats'
import { useDeleteArtifact, useNamespaceArtifacts, useUploadArtifact } from '@/hooks/useArtifacts'

// ─── Icon mapping ───────────────────────────────────────────────────

function ArtifactIcon({
  type,
  size = 20,
  className,
}: {
  type: string
  size?: number
  className?: string
}) {
  const props = { size, className }
  switch (type) {
    case 'image':
    case 'svg':
      return <Image {...props} />
    case 'audio':
      return <FileAudio {...props} />
    case 'video':
      return <FileVideo {...props} />
    case 'code':
    case 'html':
    case 'react':
      return <FileCode {...props} />
    default:
      return <File {...props} />
  }
}

// ─── File card ──────────────────────────────────────────────────────

function ArtifactCard({
  artifact,
  onDelete,
}: {
  artifact: ArtifactResponse
  onDelete: (id: string) => void
}) {
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [previewOpen, setPreviewOpen] = useState(false)
  const isImage = artifact.artifact_type === 'image' || artifact.artifact_type === 'svg'

  return (
    <div className="group relative flex flex-col overflow-hidden rounded-lg border border-black/[0.06] bg-white shadow-[0_1px_2px_rgba(0,0,0,0.04)] transition-shadow hover:shadow-[0_2px_6px_rgba(0,0,0,0.08)]">
      {/* Thumbnail / icon area */}
      <div
        className={`flex h-24 items-center justify-center bg-black/[0.02] ${isImage && artifact.content_url ? 'cursor-zoom-in' : ''}`}
        onClick={() => isImage && artifact.content_url && setPreviewOpen(true)}
      >
        {isImage && artifact.content_url ? (
          <img
            src={artifact.content_url}
            alt={artifact.filename || 'image'}
            className="max-h-full max-w-full object-contain"
          />
        ) : (
          <ArtifactIcon
            type={artifact.artifact_type}
            size={32}
            className="text-content-tertiary"
          />
        )}
      </div>

      {/* Metadata */}
      <div className="flex flex-1 flex-col gap-1 px-3 py-2">
        <div
          className="truncate text-[12px] font-medium text-content-primary"
          title={artifact.filename || artifact.artifact_id}
        >
          {artifact.filename || <span className="text-content-tertiary italic">unnamed</span>}
        </div>
        <div className="flex items-center gap-1.5">
          <span className="rounded bg-black/[0.04] px-1 py-0.5 font-mono text-[9px] uppercase tracking-wide text-content-tertiary">
            {artifact.artifact_type}
          </span>
          <span className="text-[11px] text-content-tertiary">
            {formatBytes(artifact.size_bytes)}
          </span>
        </div>
        <div className="text-[10px] text-content-tertiary">
          {new Date(artifact.created_at).toLocaleDateString()}
        </div>
      </div>

      {/* Actions */}
      <div className="absolute right-1.5 top-1.5 flex items-center gap-1 opacity-0 transition-opacity group-hover:opacity-100">
        {artifact.content_url && !isImage && (
          <a
            href={artifact.content_url}
            download={artifact.filename || undefined}
            className="rounded p-1 bg-white/80 backdrop-blur text-content-tertiary hover:text-content-primary hover:bg-white shadow-sm"
            title="Download"
            onClick={(e) => e.stopPropagation()}
          >
            <FileText size={13} />
          </a>
        )}
        {!confirmDelete ? (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation()
              setConfirmDelete(true)
            }}
            className="rounded p-1 bg-white/80 backdrop-blur text-content-tertiary hover:text-status-danger hover:bg-red-50 shadow-sm"
            title="Delete"
          >
            <Trash2 size={13} />
          </button>
        ) : (
          <div className="flex items-center gap-1 rounded bg-white px-2 py-1 shadow ring-1 ring-red-200">
            <span className="text-[11px] text-red-700">Delete?</span>
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation()
                onDelete(artifact.artifact_id)
              }}
              className="rounded px-1.5 py-0.5 bg-red-600 text-[10px] text-white hover:bg-red-700"
            >
              Yes
            </button>
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation()
                setConfirmDelete(false)
              }}
              className="rounded p-0.5 text-content-tertiary hover:text-content-primary"
            >
              <X size={12} />
            </button>
          </div>
        )}
      </div>

      {/* Lightbox */}
      {previewOpen && artifact.content_url && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/70"
          onClick={() => setPreviewOpen(false)}
        >
          <img
            src={artifact.content_url}
            alt={artifact.filename || 'preview'}
            className="max-h-[90vh] max-w-[90vw] rounded shadow-xl"
          />
        </div>
      )}
    </div>
  )
}

// ─── Tab component ──────────────────────────────────────────────────

export function NamespaceFilesTab({ namespace }: { namespace: string }) {
  const fileInputRef = useRef<HTMLInputElement>(null)
  const qc = useQueryClient()

  const { data, isLoading, isError, error } = useNamespaceArtifacts(namespace, { limit: 100 })
  const upload = useUploadArtifact()
  const del = useDeleteArtifact()

  const items = data?.items ?? []

  function handleFileSelect(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    upload.mutate(
      { file, namespace },
      {
        onSuccess: () => {
          qc.invalidateQueries({ queryKey: ['artifacts', 'namespace', namespace] })
        },
      },
    )
    // Reset so the same file can be re-uploaded after deletion.
    e.target.value = ''
  }

  return (
    <div>
      {/* Header row */}
      <div className="mb-3 flex items-center justify-between">
        <div className="text-[11px] font-semibold uppercase tracking-wider text-content-tertiary">
          Files{' '}
          {!isLoading && (
            <span className="ml-1 font-mono text-content-secondary">{data?.total ?? 0}</span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => qc.invalidateQueries({ queryKey: ['artifacts', 'namespace', namespace] })}
            className="rounded p-1 text-content-tertiary hover:text-content-primary"
            title="Refresh"
          >
            <RefreshCw size={13} />
          </button>
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            disabled={upload.isPending}
            className="inline-flex items-center gap-1.5 rounded-md bg-brand-primary px-2.5 py-1.5 text-[12px] font-medium text-white hover:bg-brand-primary/90 disabled:opacity-50"
          >
            <Upload size={12} />
            {upload.isPending ? 'Uploading…' : 'Upload file'}
          </button>
          <input
            ref={fileInputRef}
            type="file"
            className="hidden"
            onChange={handleFileSelect}
            accept="*/*"
          />
        </div>
      </div>

      {/* Error states */}
      {upload.isError && (
        <div className="mb-2 rounded-md bg-red-50 px-3 py-2 text-[12px] text-red-700 ring-1 ring-red-200">
          Upload failed: {(upload.error as Error)?.message || 'Unknown error'}
        </div>
      )}
      {isError && (
        <div className="rounded-md bg-red-50 px-3 py-2 text-[12px] text-red-700 ring-1 ring-red-200">
          Failed to load files: {(error as Error)?.message}
        </div>
      )}

      {/* Loading */}
      {isLoading && (
        <div className="py-6 text-center text-[12px] text-content-tertiary">Loading files…</div>
      )}

      {/* Empty state */}
      {!isLoading && items.length === 0 && (
        <div className="rounded-lg border border-dashed border-black/[0.08] bg-white/50 py-8 text-center">
          <File size={24} className="mx-auto text-content-tertiary" />
          <div className="mt-2 text-[12px] font-medium text-content-primary">No files yet</div>
          <div className="mt-1 text-[11px] text-content-tertiary">
            Upload a file or push one via the Chrome Extension.
          </div>
        </div>
      )}

      {/* File grid */}
      {items.length > 0 && (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4">
          {items.map((a) => (
            <ArtifactCard
              key={a.artifact_id}
              artifact={a}
              onDelete={(id) => del.mutate(id)}
            />
          ))}
        </div>
      )}
    </div>
  )
}
