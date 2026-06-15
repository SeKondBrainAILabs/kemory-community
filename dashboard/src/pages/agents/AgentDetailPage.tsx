/**
 * Memory Vault — Agent Detail Page
 *
 * EPIC-002 KMV-QA-017: Added "Generate Token" button that calls
 * POST /api/v1/agents/{id}/token and displays the resulting JWT
 * in a copyable masked field.  Token is shown only once per generation
 * and is not persisted in state across page reloads.
 */
import { useParams, useNavigate } from 'react-router-dom'
import { useState } from 'react'
import { PageShell } from '@/components/layout/PageShell'
import { StatusBadge } from '@/components/shared/StatusBadge'
import { JsonViewer } from '@/components/shared/JsonViewer'
import { ConfirmDialog } from '@/components/shared/ConfirmDialog'
import { LoadingSkeleton } from '@/components/shared/LoadingSkeleton'
import { useAgent, useAgentAction } from '@/hooks/useAgents'
import { getAgentToken } from '@/api/agents'
import { formatRelativeTime } from '@/lib/utils'
import { ArrowLeft, Play, Pause, XCircle, Key, Copy, Eye, EyeOff } from 'lucide-react'

export function AgentDetailPage() {
  const { agentId } = useParams<{ agentId: string }>()
  const navigate = useNavigate()
  const { data: agent, isLoading } = useAgent(agentId!)
  const action = useAgentAction()
  const [confirmAction, setConfirmAction] = useState<'approve' | 'suspend' | 'revoke' | null>(null)

  // Token state — KMV-QA-017
  const [token, setToken] = useState<string | null>(null)
  const [tokenVisible, setTokenVisible] = useState(false)
  const [tokenLoading, setTokenLoading] = useState(false)
  const [tokenError, setTokenError] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)

  async function handleGenerateToken() {
    if (!agentId) return
    setTokenLoading(true)
    setTokenError(null)
    try {
      const result = await getAgentToken(agentId)
      setToken(result.access_token)
      setTokenVisible(false)
    } catch {
      setTokenError('Failed to generate token. Ensure the agent is active.')
    } finally {
      setTokenLoading(false)
    }
  }

  function handleCopyToken() {
    if (!token) return
    navigator.clipboard.writeText(token).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    })
  }

  if (isLoading) {
    return (
      <PageShell>
        <LoadingSkeleton lines={6} />
      </PageShell>
    )
  }

  if (!agent) {
    return (
      <PageShell>
        <div className="rounded-lg border border-border bg-white p-8 text-center">
          <p className="text-sm text-content-secondary">
            Agent not found. It may have been revoked or the ID is invalid.
          </p>
          <button
            onClick={() => navigate('/agents')}
            className="mt-4 text-sm text-brand-primary hover:underline"
          >
            Back to agents
          </button>
        </div>
      </PageShell>
    )
  }

  return (
    <PageShell>
      <button
        onClick={() => navigate('/agents')}
        className="mb-4 flex items-center gap-1 text-sm text-content-secondary hover:text-content-primary"
      >
        <ArrowLeft size={16} /> Back to agents
      </button>

      <div className="rounded-lg border border-border bg-white p-6 shadow-sm">
        {/* Header */}
        <div className="flex items-start justify-between">
          <div>
            <h2 className="text-xl font-semibold text-content-primary">{agent.agent_name}</h2>
            <p className="mt-1 text-sm text-content-secondary">{agent.agent_description}</p>
            <div className="mt-2 flex items-center gap-2">
              <StatusBadge status={agent.status} />
              <span className="text-xs text-content-tertiary">
                Registered {formatRelativeTime(agent.registered_at)}
              </span>
            </div>
          </div>
          <div className="flex gap-2">
            {(agent.status === 'pending' || agent.status === 'pending_approval') && (
              <button
                onClick={() => setConfirmAction('approve')}
                className="flex items-center gap-1.5 rounded-lg bg-status-success px-3 py-2 text-xs font-medium text-white hover:bg-green-700"
              >
                <Play size={14} /> Approve
              </button>
            )}
            {agent.status === 'active' && (
              <button
                onClick={() => setConfirmAction('suspend')}
                className="flex items-center gap-1.5 rounded-lg bg-status-warning px-3 py-2 text-xs font-medium text-white hover:bg-amber-700"
              >
                <Pause size={14} /> Suspend
              </button>
            )}
            {agent.status === 'suspended' && (
              <button
                onClick={() => setConfirmAction('approve')}
                className="flex items-center gap-1.5 rounded-lg bg-status-success px-3 py-2 text-xs font-medium text-white hover:bg-green-700"
              >
                <Play size={14} /> Reactivate
              </button>
            )}
            {agent.status !== 'revoked' && (
              <button
                onClick={() => setConfirmAction('revoke')}
                className="flex items-center gap-1.5 rounded-lg bg-status-danger px-3 py-2 text-xs font-medium text-white hover:bg-red-700"
              >
                <XCircle size={14} /> Revoke
              </button>
            )}
          </div>
        </div>

        {/* Stats */}
        <div className="mt-6 grid grid-cols-3 gap-4">
          <div className="rounded-lg bg-surface-secondary p-4 text-center">
            <div className="text-2xl font-semibold text-content-primary">{agent.total_reads}</div>
            <div className="text-xs text-content-tertiary">Reads</div>
          </div>
          <div className="rounded-lg bg-surface-secondary p-4 text-center">
            <div className="text-2xl font-semibold text-content-primary">{agent.total_writes}</div>
            <div className="text-xs text-content-tertiary">Writes</div>
          </div>
          <div className="rounded-lg bg-surface-secondary p-4 text-center">
            <div className="text-2xl font-semibold text-status-danger">{agent.denied_requests}</div>
            <div className="text-xs text-content-tertiary">Denied</div>
          </div>
        </div>

        {/* Scopes */}
        <div className="mt-6">
          <h3 className="mb-2 text-sm font-semibold text-content-primary">Declared Scopes</h3>
          <JsonViewer data={agent.declared_scopes} />
        </div>

        {/* API Token section — KMV-QA-017 */}
        <div className="mt-6 rounded-lg border border-border bg-surface-secondary p-4">
          <div className="flex items-center justify-between">
            <div>
              <h3 className="text-sm font-semibold text-content-primary">API Token</h3>
              <p className="mt-0.5 text-xs text-content-tertiary">
                Generate a short-lived JWT for this agent to use with the Memory Vault API.
              </p>
            </div>
            <button
              onClick={handleGenerateToken}
              disabled={tokenLoading || agent.status === 'revoked'}
              className="flex items-center gap-1.5 rounded-lg border border-border bg-white px-3 py-2 text-xs font-medium text-content-primary hover:bg-surface-secondary disabled:opacity-50"
            >
              <Key size={13} />
              {tokenLoading ? 'Generating…' : 'Generate Token'}
            </button>
          </div>

          {tokenError && (
            <p className="mt-2 text-xs text-status-danger">{tokenError}</p>
          )}

          {token && (
            <div className="mt-3">
              <div className="flex items-center gap-2 rounded-lg border border-border bg-white px-3 py-2">
                <code className="flex-1 overflow-hidden text-ellipsis whitespace-nowrap text-xs text-content-primary">
                  {tokenVisible ? token : '•'.repeat(Math.min(token.length, 60))}
                </code>
                <button
                  onClick={() => setTokenVisible((v) => !v)}
                  className="shrink-0 text-content-tertiary hover:text-content-primary"
                  title={tokenVisible ? 'Hide token' : 'Show token'}
                >
                  {tokenVisible ? <EyeOff size={14} /> : <Eye size={14} />}
                </button>
                <button
                  onClick={handleCopyToken}
                  className="shrink-0 text-content-tertiary hover:text-content-primary"
                  title="Copy to clipboard"
                >
                  <Copy size={14} />
                </button>
              </div>
              {copied && (
                <p className="mt-1 text-xs text-status-success">Copied to clipboard!</p>
              )}
              <p className="mt-1 text-xs text-content-tertiary">
                This token is shown only once. Generate a new one if needed.
              </p>
            </div>
          )}
        </div>

        <div className="mt-4 text-xs text-content-tertiary">
          ID: <code className="rounded bg-surface-tertiary px-1 py-0.5">{agent.agent_id}</code>
          {agent.last_active_at && (
            <> &middot; Last active {formatRelativeTime(agent.last_active_at)}</>
          )}
        </div>
      </div>

      <ConfirmDialog
        open={confirmAction !== null}
        onOpenChange={() => setConfirmAction(null)}
        title={`${confirmAction?.charAt(0).toUpperCase()}${confirmAction?.slice(1)} Agent`}
        description={`Are you sure you want to ${confirmAction} "${agent.agent_name}"?`}
        confirmLabel={confirmAction?.charAt(0).toUpperCase() + (confirmAction?.slice(1) ?? '')}
        variant={confirmAction === 'revoke' ? 'danger' : 'default'}
        onConfirm={() => {
          if (confirmAction) {
            action.mutate({ agentId: agent.agent_id, action: confirmAction })
          }
        }}
      />
    </PageShell>
  )
}
