/**
 * Memory Vault — Agent List Page
 *
 * EPIC-002 KMV-QA-016: Added inline Approve / Suspend / Revoke action
 * buttons in the Actions column so admins can act on agents without
 * navigating to the detail page.  The action buttons are context-aware
 * (e.g. "Approve" only shows for pending agents, "Revoke" only for active).
 *
 * BUG-003 fix: Added "Register Agent" button and modal form so users can
 * register new agents directly from the list page without navigating away.
 */
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { type ColumnDef, type Row } from '@tanstack/react-table'
import * as Dialog from '@radix-ui/react-dialog'
import { PageShell } from '@/components/layout/PageShell'
import { DataTable } from '@/components/shared/DataTable'
import { StatusBadge } from '@/components/shared/StatusBadge'
import { LoadingSkeleton } from '@/components/shared/LoadingSkeleton'
import { ConfirmDialog } from '@/components/shared/ConfirmDialog'
import { useAgents, useAgentAction, useDeleteAgent, useRegisterAgent } from '@/hooks/useAgents'
import { formatRelativeTime } from '@/lib/utils'
import type { AgentResponse } from '@/api/types'
import { cn } from '@/lib/utils'
import { CheckCircle, PauseCircle, XCircle, Trash2, Plus, X } from 'lucide-react'

const statusFilters = ['all', 'pending', 'active', 'suspended', 'revoked'] as const

type AgentActionType = 'approve' | 'suspend' | 'revoke'

interface PendingAction {
  agentId: string
  agentName: string
  action: AgentActionType
}

// ─── Register Agent Modal ─────────────────────────────────────────

interface RegisterAgentForm {
  agent_name: string
  agent_description: string
  callback_url: string
}

function RegisterAgentModal({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const register = useRegisterAgent()
  const [form, setForm] = useState<RegisterAgentForm>({
    agent_name: '',
    agent_description: '',
    callback_url: '',
  })
  const [apiKey, setApiKey] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  function handleChange(e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) {
    setForm((prev) => ({ ...prev, [e.target.name]: e.target.value }))
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    try {
      const result = await register.mutateAsync({
        agent_name: form.agent_name.trim(),
        agent_description: form.agent_description.trim(),
        declared_scopes: [
          { scope: 'memory:read', reason: 'Read memories from vault' },
          { scope: 'memory:write', reason: 'Write memories to vault' },
        ],
        callback_url: form.callback_url.trim() || undefined,
      })
      setApiKey(result.api_key)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Registration failed')
    }
  }

  function handleClose() {
    setForm({ agent_name: '', agent_description: '', callback_url: '' })
    setApiKey(null)
    setError(null)
    onOpenChange(false)
  }

  return (
    <Dialog.Root open={open} onOpenChange={handleClose}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/40" />
        <Dialog.Content className="fixed left-1/2 top-1/2 z-50 w-full max-w-lg -translate-x-1/2 -translate-y-1/2 rounded-xl border border-border bg-white p-6 shadow-lg">
          <Dialog.Title className="text-base font-semibold text-content-primary">
            Register New Agent
          </Dialog.Title>
          <Dialog.Description className="mt-1 text-sm text-content-secondary">
            Register an agent to grant it controlled access to the memory vault.
          </Dialog.Description>

          {apiKey ? (
            /* Success state — show the API key once */
            <div className="mt-4 space-y-4">
              <div className="rounded-lg border border-green-200 bg-green-50 p-4">
                <p className="text-sm font-medium text-green-800">Agent registered successfully!</p>
                <p className="mt-1 text-xs text-green-700">
                  Copy the API key below — it will not be shown again.
                </p>
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-content-secondary">
                  API Key
                </label>
                <div className="flex items-center gap-2">
                  <code className="flex-1 rounded border border-border bg-surface-secondary px-3 py-2 text-xs font-mono break-all">
                    {apiKey}
                  </code>
                  <button
                    type="button"
                    onClick={() => navigator.clipboard.writeText(apiKey)}
                    className="rounded border border-border px-3 py-2 text-xs text-content-secondary hover:bg-surface-secondary"
                  >
                    Copy
                  </button>
                </div>
              </div>
              <div className="flex justify-end">
                <button
                  type="button"
                  onClick={handleClose}
                  className="rounded-lg bg-brand-primary px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700"
                >
                  Done
                </button>
              </div>
            </div>
          ) : (
            /* Registration form */
            <form onSubmit={handleSubmit} className="mt-4 space-y-4">
              <div>
                <label htmlFor="agent_name" className="mb-1 block text-xs font-medium text-content-secondary">
                  Agent Name <span className="text-status-danger">*</span>
                </label>
                <input
                  id="agent_name"
                  name="agent_name"
                  type="text"
                  required
                  value={form.agent_name}
                  onChange={handleChange}
                  placeholder="e.g. my-summariser-bot"
                  className="w-full rounded-lg border border-border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-primary"
                />
              </div>

              <div>
                <label htmlFor="agent_description" className="mb-1 block text-xs font-medium text-content-secondary">
                  Description <span className="text-status-danger">*</span>
                </label>
                <textarea
                  id="agent_description"
                  name="agent_description"
                  required
                  rows={3}
                  value={form.agent_description}
                  onChange={handleChange}
                  placeholder="What does this agent do?"
                  className="w-full rounded-lg border border-border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-primary"
                />
              </div>

              <div>
                <label htmlFor="callback_url" className="mb-1 block text-xs font-medium text-content-secondary">
                  Callback URL <span className="text-content-tertiary">(optional)</span>
                </label>
                <input
                  id="callback_url"
                  name="callback_url"
                  type="url"
                  value={form.callback_url}
                  onChange={handleChange}
                  placeholder="https://your-agent.example.com/callback"
                  className="w-full rounded-lg border border-border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-primary"
                />
              </div>

              {error && (
                <p className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
                  {error}
                </p>
              )}

              <div className="flex justify-end gap-3 pt-2">
                <button
                  type="button"
                  onClick={handleClose}
                  className="rounded-lg border border-border px-4 py-2 text-sm font-medium text-content-secondary hover:bg-surface-secondary"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={register.isPending}
                  className="rounded-lg bg-brand-primary px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-60"
                >
                  {register.isPending ? 'Registering…' : 'Register Agent'}
                </button>
              </div>
            </form>
          )}

          <Dialog.Close asChild>
            <button
              onClick={handleClose}
              className="absolute right-4 top-4 text-content-tertiary hover:text-content-primary"
            >
              <X size={16} />
            </button>
          </Dialog.Close>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}

// ─── Action buttons inside each table row ─────────────────────────

function AgentActionButtons({
  agent,
  onAction,
  onDelete,
  isPending,
}: {
  agent: AgentResponse
  onAction: (action: AgentActionType) => void
  onDelete: () => void
  isPending: boolean
}) {
  return (
    <div className="flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
      {agent.status === 'revoked' && (
        <button
          onClick={() => {
            if (confirm(`Delete ${agent.agent_name}? This cannot be undone.`)) onDelete()
          }}
          disabled={isPending}
          title="Delete"
          className="rounded p-1.5 text-content-tertiary hover:bg-red-50 hover:text-status-danger disabled:opacity-40"
        >
          <Trash2 size={15} />
        </button>
      )}
      {agent.status === 'pending' && (
        <button
          onClick={() => onAction('approve')}
          disabled={isPending}
          title="Approve"
          className="rounded p-1.5 text-status-success hover:bg-green-50 disabled:opacity-40"
        >
          <CheckCircle size={15} />
        </button>
      )}
      {(agent.status === 'active' || agent.status === 'pending') && (
        <button
          onClick={() => onAction('suspend')}
          disabled={isPending}
          title="Suspend"
          className="rounded p-1.5 text-status-warning hover:bg-amber-50 disabled:opacity-40"
        >
          <PauseCircle size={15} />
        </button>
      )}
      {agent.status !== 'revoked' && (
        <button
          onClick={() => onAction('revoke')}
          disabled={isPending}
          title="Revoke"
          className="rounded p-1.5 text-status-danger hover:bg-red-50 disabled:opacity-40"
        >
          <XCircle size={15} />
        </button>
      )}
    </div>
  )
}

// ─── Page ─────────────────────────────────────────────────────────

export function AgentListPage() {
  const [filter, setFilter] = useState<string>('all')
  const [pendingAction, setPendingAction] = useState<PendingAction | null>(null)
  const [registerOpen, setRegisterOpen] = useState(false)
  const agents = useAgents(filter === 'all' ? undefined : filter)
  const navigate = useNavigate()
  const action = useAgentAction()
  const deleteAgent = useDeleteAgent()

  // Build columns inside the component so action handlers have access to state
  const columns: ColumnDef<AgentResponse, unknown>[] = [
    { accessorKey: 'agent_name', header: 'Name' },
    {
      accessorKey: 'status',
      header: 'Status',
      cell: ({ getValue }) => <StatusBadge status={getValue() as string} />,
    },
    {
      accessorKey: 'agent_description',
      header: 'Description',
      cell: ({ getValue }) => (
        <span className="line-clamp-1 max-w-xs text-sm text-content-secondary">
          {getValue() as string}
        </span>
      ),
    },
    {
      accessorKey: 'registered_at',
      header: 'Registered',
      cell: ({ getValue }) => formatRelativeTime(getValue() as string),
    },
    { accessorKey: 'total_reads', header: 'Reads' },
    { accessorKey: 'total_writes', header: 'Writes' },
    { accessorKey: 'denied_requests', header: 'Denied' },
    {
      id: 'actions',
      header: 'Actions',
      cell: ({ row }: { row: Row<AgentResponse> }) => (
        <AgentActionButtons
          agent={row.original}
          isPending={action.isPending || deleteAgent.isPending}
          onDelete={() => deleteAgent.mutate(row.original.agent_id)}
          onAction={(act) =>
            setPendingAction({
              agentId: row.original.agent_id,
              agentName: row.original.agent_name,
              action: act,
            })
          }
        />
      ),
    },
  ]

  function confirmAction() {
    if (!pendingAction) return
    action.mutate(
      { agentId: pendingAction.agentId, action: pendingAction.action },
      { onSettled: () => setPendingAction(null) },
    )
  }

  const actionLabels: Record<AgentActionType, string> = {
    approve: 'Approve',
    suspend: 'Suspend',
    revoke: 'Revoke',
  }

  return (
    <PageShell>
      {/* Toolbar: status filter pills + Register button */}
      <div className="mb-4 flex items-center justify-between gap-2">
        <div className="flex flex-wrap gap-2">
          {statusFilters.map((s) => (
            <button
              key={s}
              onClick={() => setFilter(s)}
              className={cn(
                'rounded-full px-4 py-1.5 text-xs font-medium capitalize transition-colors',
                filter === s
                  ? 'bg-brand-primary text-white'
                  : 'border border-border bg-white text-content-secondary hover:bg-surface-secondary',
              )}
            >
              {s}
            </button>
          ))}
        </div>

        {/* BUG-003 fix: Register Agent button */}
        <button
          onClick={() => setRegisterOpen(true)}
          className="flex items-center gap-1.5 rounded-lg bg-brand-primary px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700"
        >
          <Plus size={15} />
          Register Agent
        </button>
      </div>

      {agents.isLoading ? (
        <LoadingSkeleton lines={8} />
      ) : agents.data ? (
        <DataTable
          columns={columns}
          data={agents.data}
          onRowClick={(row) => navigate(`/agents/${row.agent_id}`)}
        />
      ) : (
        <p className="py-8 text-center text-sm text-content-tertiary">No agents found.</p>
      )}

      {/* Register Agent modal */}
      <RegisterAgentModal open={registerOpen} onOpenChange={setRegisterOpen} />

      {/* Confirm action dialog */}
      <ConfirmDialog
        open={pendingAction !== null}
        onOpenChange={() => setPendingAction(null)}
        title={`${pendingAction ? actionLabels[pendingAction.action] : ''} Agent`}
        description={`Are you sure you want to ${pendingAction?.action} "${pendingAction?.agentName}"?`}
        confirmLabel={pendingAction ? actionLabels[pendingAction.action] : ''}
        variant={pendingAction?.action === 'revoke' ? 'danger' : 'default'}
        onConfirm={confirmAction}
      />
    </PageShell>
  )
}
