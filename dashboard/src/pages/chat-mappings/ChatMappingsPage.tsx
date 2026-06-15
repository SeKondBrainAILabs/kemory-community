/**
 * Kemory dashboard — Chat namespace mappings page (chats-v1 UI).
 *
 * Lets the user collapse (platform, project) combinations onto Kemory
 * namespaces — many-to-one by design. Backed by /api/v1/chat-mappings
 * (v3.31.0).
 *
 * UX:
 *   - Table of mappings sorted by priority (low evaluated first)
 *   - "New mapping" dialog with platform select + exact-id OR pattern
 *   - Inline toggle for `enabled`
 *   - Delete with confirm
 */
import { useState } from 'react'
import * as Dialog from '@radix-ui/react-dialog'
import { Plus, Trash2, X } from 'lucide-react'
import { useMemo } from 'react'
import type { ColumnDef } from '@tanstack/react-table'
import { PageShell } from '@/components/layout/PageShell'
import { DataTable } from '@/components/shared/DataTable'
import { ConfirmDialog } from '@/components/shared/ConfirmDialog'
import {
  useChatMappings,
  useCreateChatMapping,
  useDeleteChatMapping,
  useUpdateChatMapping,
} from '@/hooks/useChatMappings'
import type { ChatMappingResponse } from '@/api/chatMappings'
import type { Platform } from '@/api/chats'

const PLATFORMS: Array<{ value: Platform; label: string }> = [
  { value: 'chatgpt', label: 'ChatGPT' },
  { value: 'claude', label: 'Claude' },
  { value: 'gemini', label: 'Gemini' },
  { value: 'manus', label: 'Manus' },
  { value: 'other', label: 'Other' },
]

interface FormState {
  platform: Platform
  matchKind: 'project_id' | 'pattern'
  source_project_id: string
  source_project_name_pattern: string
  target_namespace: string
  priority: number
  enabled: boolean
}

const EMPTY_FORM: FormState = {
  platform: 'claude',
  matchKind: 'project_id',
  source_project_id: '',
  source_project_name_pattern: '',
  target_namespace: '',
  priority: 100,
  enabled: true,
}

export function ChatMappingsPage() {
  const { data: mappings, isLoading, isError, error } = useChatMappings()
  const createMutation = useCreateChatMapping()
  const updateMutation = useUpdateChatMapping()
  const deleteMutation = useDeleteChatMapping()

  const [dialogOpen, setDialogOpen] = useState(false)
  const [form, setForm] = useState<FormState>(EMPTY_FORM)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [confirmDelete, setConfirmDelete] = useState<ChatMappingResponse | null>(null)

  function resetForm() {
    setForm(EMPTY_FORM)
    setSubmitError(null)
  }

  function handleCreate(e: React.FormEvent) {
    e.preventDefault()
    setSubmitError(null)
    // Form validation: target_namespace required; one of project_id / pattern required
    if (!form.target_namespace.trim()) {
      setSubmitError('target_namespace is required')
      return
    }
    const usingId = form.matchKind === 'project_id'
    if (usingId && !form.source_project_id.trim()) {
      setSubmitError('source_project_id is required when matching by id')
      return
    }
    if (!usingId && !form.source_project_name_pattern.trim()) {
      setSubmitError('source_project_name_pattern is required when matching by pattern')
      return
    }
    createMutation.mutate(
      {
        platform: form.platform,
        source_project_id: usingId ? form.source_project_id.trim() : null,
        source_project_name_pattern: usingId
          ? null
          : form.source_project_name_pattern.trim(),
        target_namespace: form.target_namespace.trim(),
        priority: form.priority,
        enabled: form.enabled,
      },
      {
        onSuccess: () => {
          setDialogOpen(false)
          resetForm()
        },
        onError: (err) => {
          setSubmitError((err as Error).message ?? 'Failed to create mapping')
        },
      },
    )
  }

  function handleToggleEnabled(row: ChatMappingResponse) {
    updateMutation.mutate({
      mappingId: row.mapping_id,
      data: { enabled: !row.enabled },
    })
  }

  function handleDelete() {
    if (!confirmDelete) return
    deleteMutation.mutate(confirmDelete.mapping_id, {
      onSuccess: () => setConfirmDelete(null),
    })
  }

  const columns = useMemo<ColumnDef<ChatMappingResponse>[]>(
    () => [
      {
        accessorKey: 'platform',
        header: 'Platform',
        cell: ({ row }) => (
          <span className="font-medium capitalize text-content-primary">
            {row.original.platform}
          </span>
        ),
      },
      {
        id: 'match',
        header: 'Match',
        cell: ({ row }) =>
          row.original.source_project_id ? (
            <span className="font-mono text-xs">
              id: {row.original.source_project_id}
            </span>
          ) : row.original.source_project_name_pattern ? (
            <span className="font-mono text-xs">
              pattern: {row.original.source_project_name_pattern}
            </span>
          ) : (
            <span className="text-xs text-content-tertiary">(any)</span>
          ),
      },
      {
        accessorKey: 'target_namespace',
        header: '→ Namespace',
        cell: ({ row }) => (
          <span className="font-mono text-xs text-content-primary">
            {row.original.target_namespace}
          </span>
        ),
      },
      {
        accessorKey: 'priority',
        header: 'Priority',
        cell: ({ row }) => <span className="tabular-nums">{row.original.priority}</span>,
      },
      {
        id: 'enabled',
        header: 'Enabled',
        cell: ({ row }) => (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation()
              handleToggleEnabled(row.original)
            }}
            className={`rounded-full px-2 py-0.5 text-xs font-medium ${
              row.original.enabled
                ? 'bg-emerald-50 text-emerald-700'
                : 'bg-gray-100 text-content-secondary'
            }`}
          >
            {row.original.enabled ? 'On' : 'Off'}
          </button>
        ),
      },
      {
        id: 'actions',
        header: '',
        cell: ({ row }) => (
          <div className="flex justify-end">
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation()
                setConfirmDelete(row.original)
              }}
              className="rounded p-1 text-content-tertiary hover:bg-red-50 hover:text-status-danger"
              title="Delete mapping"
            >
              <Trash2 size={14} />
            </button>
          </div>
        ),
      },
    ],
    // updateMutation reference doesn't need to flow through here — the
    // handlers close over the latest hook instance fine for these
    // ephemeral cells.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  )

  return (
    <PageShell>
      <div className="mb-4 flex items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-content-primary">Chat mappings</h1>
          <p className="mt-1 text-sm text-content-secondary">
            Route chats from a source platform / project to a specific Kemory
            namespace. Many mappings can point at the same namespace — that's
            how you collapse projects across tools.
          </p>
        </div>
        <button
          type="button"
          onClick={() => {
            resetForm()
            setDialogOpen(true)
          }}
          className="inline-flex items-center gap-1.5 rounded-lg bg-brand-primary px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-700"
        >
          <Plus size={14} />
          New mapping
        </button>
      </div>

      {isLoading ? (
        <div className="rounded-lg border border-border bg-white p-8 text-center text-sm text-content-tertiary">
          Loading mappings…
        </div>
      ) : isError ? (
        <div className="rounded-lg border border-status-danger bg-red-50 p-8 text-center text-sm text-status-danger">
          Failed to load mappings. {(error as Error)?.message}
        </div>
      ) : (
        <DataTable columns={columns} data={mappings ?? []} />
      )}

      <Dialog.Root open={dialogOpen} onOpenChange={setDialogOpen}>
        <Dialog.Portal>
          <Dialog.Overlay className="fixed inset-0 z-50 bg-black/40" />
          <Dialog.Content className="fixed left-1/2 top-1/2 z-50 w-full max-w-md -translate-x-1/2 -translate-y-1/2 rounded-xl border border-border bg-white p-6 shadow-lg">
            <Dialog.Title className="text-base font-semibold text-content-primary">
              New chat mapping
            </Dialog.Title>
            <Dialog.Description className="mt-1 text-sm text-content-secondary">
              Chats matching this rule will land in the target namespace,
              skipping the auto-matcher.
            </Dialog.Description>
            <form onSubmit={handleCreate} className="mt-4 space-y-3 text-sm">
              <div>
                <label className="mb-1 block text-xs font-medium text-content-secondary">
                  Platform
                </label>
                <select
                  value={form.platform}
                  onChange={(e) =>
                    setForm({ ...form, platform: e.target.value as Platform })
                  }
                  className="w-full rounded-lg border border-border bg-white px-3 py-2 text-sm focus:border-brand-primary focus:outline-none"
                >
                  {PLATFORMS.map((p) => (
                    <option key={p.value} value={p.value}>
                      {p.label}
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label className="mb-1 block text-xs font-medium text-content-secondary">
                  Match by
                </label>
                <div className="flex gap-2 text-xs">
                  <button
                    type="button"
                    onClick={() => setForm({ ...form, matchKind: 'project_id' })}
                    className={`rounded-lg border px-3 py-1.5 ${
                      form.matchKind === 'project_id'
                        ? 'border-brand-primary bg-brand-primary/10 text-brand-primary'
                        : 'border-border text-content-secondary'
                    }`}
                  >
                    Project ID (exact)
                  </button>
                  <button
                    type="button"
                    onClick={() => setForm({ ...form, matchKind: 'pattern' })}
                    className={`rounded-lg border px-3 py-1.5 ${
                      form.matchKind === 'pattern'
                        ? 'border-brand-primary bg-brand-primary/10 text-brand-primary'
                        : 'border-border text-content-secondary'
                    }`}
                  >
                    Name pattern
                  </button>
                </div>
              </div>

              {form.matchKind === 'project_id' ? (
                <div>
                  <label className="mb-1 block text-xs font-medium text-content-secondary">
                    Source project ID
                  </label>
                  <input
                    type="text"
                    value={form.source_project_id}
                    onChange={(e) =>
                      setForm({ ...form, source_project_id: e.target.value })
                    }
                    placeholder="e.g. proj-xyz from the source tool"
                    className="w-full rounded-lg border border-border bg-white px-3 py-2 text-sm font-mono focus:border-brand-primary focus:outline-none"
                  />
                </div>
              ) : (
                <div>
                  <label className="mb-1 block text-xs font-medium text-content-secondary">
                    Project name pattern
                  </label>
                  <input
                    type="text"
                    value={form.source_project_name_pattern}
                    onChange={(e) =>
                      setForm({
                        ...form,
                        source_project_name_pattern: e.target.value,
                      })
                    }
                    placeholder="case-insensitive substring (e.g. 'steady quill')"
                    className="w-full rounded-lg border border-border bg-white px-3 py-2 text-sm focus:border-brand-primary focus:outline-none"
                  />
                </div>
              )}

              <div>
                <label className="mb-1 block text-xs font-medium text-content-secondary">
                  Target namespace
                </label>
                <input
                  type="text"
                  value={form.target_namespace}
                  onChange={(e) =>
                    setForm({ ...form, target_namespace: e.target.value })
                  }
                  placeholder="e.g. project:steady-quill"
                  className="w-full rounded-lg border border-border bg-white px-3 py-2 text-sm font-mono focus:border-brand-primary focus:outline-none"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="mb-1 block text-xs font-medium text-content-secondary">
                    Priority
                  </label>
                  <input
                    type="number"
                    min={0}
                    max={10000}
                    value={form.priority}
                    onChange={(e) =>
                      setForm({ ...form, priority: parseInt(e.target.value || '0', 10) })
                    }
                    className="w-full rounded-lg border border-border bg-white px-3 py-2 text-sm focus:border-brand-primary focus:outline-none"
                  />
                </div>
                <div>
                  <label className="mb-1 block text-xs font-medium text-content-secondary">
                    Enabled
                  </label>
                  <button
                    type="button"
                    onClick={() => setForm({ ...form, enabled: !form.enabled })}
                    className={`w-full rounded-lg border px-3 py-2 text-sm font-medium ${
                      form.enabled
                        ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
                        : 'border-border bg-white text-content-secondary'
                    }`}
                  >
                    {form.enabled ? 'On' : 'Off'}
                  </button>
                </div>
              </div>

              {submitError && (
                <div className="rounded border border-status-danger bg-red-50 p-2 text-xs text-status-danger">
                  {submitError}
                </div>
              )}

              <div className="mt-4 flex justify-end gap-2">
                <button
                  type="button"
                  onClick={() => setDialogOpen(false)}
                  className="rounded-lg border border-border px-4 py-2 text-sm font-medium text-content-secondary hover:bg-surface-secondary"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={createMutation.isPending}
                  className="rounded-lg bg-brand-primary px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
                >
                  {createMutation.isPending ? 'Creating…' : 'Create mapping'}
                </button>
              </div>
            </form>
            <Dialog.Close asChild>
              <button className="absolute right-4 top-4 text-content-tertiary hover:text-content-primary">
                <X size={16} />
              </button>
            </Dialog.Close>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>

      <ConfirmDialog
        open={!!confirmDelete}
        onOpenChange={(open) => !open && setConfirmDelete(null)}
        title="Delete mapping?"
        description={
          confirmDelete
            ? `Chats matching (${confirmDelete.platform}, ${confirmDelete.source_project_id ?? confirmDelete.source_project_name_pattern}) will no longer be routed to "${confirmDelete.target_namespace}". The namespace matcher will resume choosing for them.`
            : ''
        }
        confirmLabel="Delete"
        variant="danger"
        onConfirm={handleDelete}
      />
    </PageShell>
  )
}
