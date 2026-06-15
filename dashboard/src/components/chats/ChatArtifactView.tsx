/**
 * Renders one artifact attached to a chat turn.
 *
 * Type matrix:
 *   image  → <img>   (when content_url is set)
 *   audio  → <audio controls> (v3.33.0)
 *   video  → <video controls> (v3.33.0)
 *   code   → <pre> with the inline content
 *   html / react / svg → <pre> too — no syntax highlighter dep
 *   file   → header + Download button; if content_url is set, opens
 *            the signed minio URL; otherwise an empty placeholder
 *
 * Filename / mimetype / size_bytes come from artifact_metadata
 * (populated by the minio upload endpoint or the extension).
 */
import {
  Code,
  Download,
  FileText,
  FileQuestion,
  Image as ImageIcon,
  Music,
  Video as VideoIcon,
} from 'lucide-react'
import type { ArtifactResponse } from '@/api/chats'

interface Props {
  artifact: ArtifactResponse
}

const TYPE_ICON: Record<string, typeof Code> = {
  code: Code,
  html: Code,
  react: Code,
  svg: Code,
  image: ImageIcon,
  file: FileText,
  audio: Music,
  video: VideoIcon,
}

function formatBytes(n: number | undefined | null): string {
  if (!n || n <= 0) return ''
  const units = ['B', 'KB', 'MB', 'GB']
  let v = n
  let u = 0
  while (v >= 1024 && u < units.length - 1) {
    v /= 1024
    u++
  }
  return `${v.toFixed(v < 10 && u > 0 ? 1 : 0)} ${units[u]}`
}

export function ChatArtifactView({ artifact }: Props) {
  const Icon = TYPE_ICON[artifact.artifact_type] ?? FileQuestion
  const meta = (artifact.artifact_metadata ?? {}) as Record<string, unknown>
  const filename = (meta.filename as string | undefined) ?? undefined
  const mimetype = (meta.mimetype as string | undefined) ?? undefined
  const sizeBytes = (meta.size_bytes as number | undefined) ?? undefined
  const sizeStr = formatBytes(sizeBytes)

  const label =
    filename ??
    (artifact.language
      ? `${artifact.artifact_type} · ${artifact.language}`
      : artifact.artifact_type)

  const subline = [mimetype, sizeStr].filter(Boolean).join(' · ')

  // chats-v1 v3.33.0: audio + video render with native HTML controls
  // when we have a content_url (which the backend signs on read for
  // minio-backed bodies). file falls through to a download button.
  const isAudio = artifact.artifact_type === 'audio'
  const isVideo = artifact.artifact_type === 'video'
  const isImage = artifact.artifact_type === 'image'

  return (
    <div className="rounded-md border border-border bg-surface-secondary/50 p-3">
      <div className="mb-2 flex items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2 text-xs font-medium text-content-secondary">
          <Icon size={14} />
          <div className="min-w-0">
            <div className="truncate" title={label}>
              {label}
            </div>
            {subline && (
              <div className="truncate text-[10px] font-normal text-content-tertiary">
                {subline}
              </div>
            )}
          </div>
        </div>
        {(filename || artifact.content_url) && (
          <a
            href={artifact.content_url ?? '#'}
            download={filename}
            target="_blank"
            rel="noreferrer"
            className="inline-flex shrink-0 items-center gap-1 rounded border border-border bg-white px-2 py-0.5 text-[10px] font-medium text-content-secondary hover:bg-surface-secondary"
            title="Download"
          >
            <Download size={11} /> Download
          </a>
        )}
      </div>

      {isAudio && artifact.content_url ? (
        <audio
          controls
          preload="metadata"
          src={artifact.content_url}
          className="w-full"
        />
      ) : isVideo && artifact.content_url ? (
        <video
          controls
          preload="metadata"
          src={artifact.content_url}
          className="max-h-96 w-full rounded border border-border bg-black"
        />
      ) : isImage && artifact.content_url ? (
        <img
          src={artifact.content_url}
          alt={filename ?? artifact.artifact_type}
          className="max-h-72 max-w-full rounded border border-border"
        />
      ) : artifact.content ? (
        <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-words rounded bg-white p-2 font-mono text-[11px] text-content-primary">
          {artifact.content}
        </pre>
      ) : artifact.content_url ? (
        <a
          href={artifact.content_url}
          target="_blank"
          rel="noreferrer"
          className="text-xs text-brand-primary underline"
        >
          Open artifact (external)
        </a>
      ) : (
        <div className="text-xs text-content-tertiary">
          Empty artifact (sha256 {artifact.content_sha256.slice(0, 10)}…)
        </div>
      )}
    </div>
  )
}
