/**
 * Full-page wrapper at /chats/:chatId — used for permalinks and direct
 * navigation. The same `ChatDetailPanel` content is reused so panel +
 * page never drift.
 */
import { Link, useParams } from 'react-router-dom'
import { ArrowLeft } from 'lucide-react'
import { PageShell } from '@/components/layout/PageShell'
import { ChatDetailPanel } from './ChatDetailPanel'

export function ChatDetailPage() {
  const { chatId } = useParams<{ chatId: string }>()

  return (
    <PageShell>
      <div className="mb-3">
        <Link
          to="/chats"
          className="inline-flex items-center gap-1 text-sm text-content-secondary hover:text-content-primary"
        >
          <ArrowLeft size={14} />
          All chats
        </Link>
      </div>
      <div className="overflow-hidden rounded-lg border border-border bg-white">
        <ChatDetailPanel chatId={chatId ?? null} />
      </div>
    </PageShell>
  )
}
