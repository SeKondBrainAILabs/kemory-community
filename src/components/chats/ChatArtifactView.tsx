/**
 * Renders one artifact attached to a chat turn.
 *
 * v1 keeps it simple: code/text artifacts go into a <pre>; images render
 * inline when `content_url` is set; the rest get a download link or a
 * compact "binary artifact (N bytes)" placeholder. No syntax highlighter
 * dependency added for this — the codebase doesn't have one wired and
 * the plan says "don't add a new dep just for this."
 */
import { Code, FileText, Image as ImageIcon, FileQuestion } from 'lucide-react'
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
}

export function ChatArtifactView({ artifact }: Props) {
  const Icon = TYPE_ICON[artifact.artifact_type] ?? FileQuestion
  const label = artifact.language
    ? `${artifact.artifact_type} · ${artifact.language}`
    : artifact.artifact_type

  return (
    <div className="rounded-md border border-border bg-surface-secondary/50 p-3">
      <div className="mb-2 flex items-center gap-2 text-xs font-medium text-content-secondary">
        <Icon size={14} />
        <span className="capitalize">{label}</span>
      </div>

      {artifact.artifact_type === 'image' && artifact.content_url ? (
        <img
          src={artifact.content_url}
          alt={artifact.artifact_type}
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
