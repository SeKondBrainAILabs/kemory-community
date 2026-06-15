/**
 * Renders one turn (user / assistant / system / tool) in the chat detail
 * panel.
 *
 * Layout:
 *   ┌─ Role pill ──── timestamp (if present) ───┐
 *   │  whitespace-pre-wrap content              │
 *   │  ⮑ thinking block (collapsed by default)  │
 *   │  ⮑ tool_calls (JSON viewer)               │
 *   │  ⮑ artifacts (one per row)                │
 *   └────────────────────────────────────────────┘
 *
 * Content is rendered as plain text (preserving line breaks). The
 * existing dashboard doesn't bundle a markdown renderer and the plan
 * explicitly avoids adding one for this phase. If we want
 * markdown later, swap the `<p>` for an MDX/markdown component without
 * touching anything else.
 */
import { useState } from 'react'
import { Brain, ChevronDown, ChevronRight, Wrench } from 'lucide-react'
import type { TurnResponse } from '@/api/chats'
import { cn } from '@/lib/utils'
import { ChatArtifactView } from './ChatArtifactView'

interface Props {
  turn: TurnResponse
}

const ROLE_PILL: Record<string, string> = {
  user: 'bg-brand-primary/10 text-brand-primary border-brand-primary/30',
  assistant: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  system: 'bg-amber-50 text-amber-700 border-amber-200',
  tool: 'bg-purple-50 text-purple-700 border-purple-200',
}

export function ChatTurnView({ turn }: Props) {
  const [thinkingOpen, setThinkingOpen] = useState(false)
  const [toolCallsOpen, setToolCallsOpen] = useState(false)

  const pillClass = ROLE_PILL[turn.role] ?? 'bg-gray-50 text-content-secondary border-gray-200'

  return (
    <div className="rounded-lg border border-border bg-white p-3">
      <div className="mb-2 flex items-center justify-between">
        <span
          className={cn(
            'inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium capitalize',
            pillClass,
          )}
        >
          {turn.role}
        </span>
        <span className="font-mono text-[10px] text-content-tertiary">#{turn.sequence}</span>
      </div>

      {turn.content && (
        <p className="whitespace-pre-wrap break-words text-sm text-content-primary">{turn.content}</p>
      )}

      {turn.thinking_content && (
        <div className="mt-2 rounded border border-dashed border-border bg-surface-secondary/40 p-2">
          <button
            type="button"
            onClick={() => setThinkingOpen((v) => !v)}
            className="flex w-full items-center gap-1 text-xs font-medium text-content-secondary"
          >
            {thinkingOpen ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
            <Brain size={12} />
            Thinking
          </button>
          {thinkingOpen && (
            <p className="mt-2 whitespace-pre-wrap break-words text-xs text-content-secondary">
              {turn.thinking_content}
            </p>
          )}
        </div>
      )}

      {turn.tool_calls && turn.tool_calls.length > 0 && (
        <div className="mt-2 rounded border border-dashed border-border bg-surface-secondary/40 p-2">
          <button
            type="button"
            onClick={() => setToolCallsOpen((v) => !v)}
            className="flex w-full items-center gap-1 text-xs font-medium text-content-secondary"
          >
            {toolCallsOpen ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
            <Wrench size={12} />
            {turn.tool_calls.length} tool call{turn.tool_calls.length > 1 ? 's' : ''}
          </button>
          {toolCallsOpen && (
            <pre className="mt-2 max-h-48 overflow-auto rounded bg-white p-2 font-mono text-[10px] text-content-primary">
              {JSON.stringify(turn.tool_calls, null, 2)}
            </pre>
          )}
        </div>
      )}

      {turn.artifacts && turn.artifacts.length > 0 && (
        <div className="mt-2 space-y-2">
          {turn.artifacts.map((art) => (
            <ChatArtifactView key={art.artifact_id} artifact={art} />
          ))}
        </div>
      )}
    </div>
  )
}
