/**
 * Memory Vault — Permission List Page
 *
 * EPIC-003 fixes:
 *   KMV-QA-023: Add namespace_filter input to the "Add Rule" form
 *   KMV-QA-024: Add enable/disable toggle button in the Actions column
 */
import { useState, useMemo } from 'react'
import { type ColumnDef, type Row } from '@tanstack/react-table'
import { PageShell } from '@/components/layout/PageShell'
import { DataTable } from '@/components/shared/DataTable'
import { StatusBadge } from '@/components/shared/StatusBadge'
import { ConfirmDialog } from '@/components/shared/ConfirmDialog'
import { LoadingSkeleton } from '@/components/shared/LoadingSkeleton'
import {
  usePermissions,
  useCreatePermission,
  useDeletePermission,
  useTogglePermission,
} from '@/hooks/usePermissions'
import { useAgents } from '@/hooks/useAgents'
import type { PermissionRuleResponse, PermissionRuleCreate, ValidAction } from '@/api/types'
import { VALID_SCOPES, VALID_ACTIONS } from '@/api/types'
import { Plus, Trash2, ToggleLeft, ToggleRight } from 'lucide-react'

export function PermissionListPage() {
  const permissions = usePermissions()
  const agents = useAgents()
  const createMut = useCreatePermission()
  const deleteMut = useDeletePermission()
  const toggleMut = useTogglePermission()
  const [showForm, setShowForm] = useState(false)
  const [deleteId, setDeleteId] = useState<string | null>(null)
  const [form, setForm] = useState<PermissionRuleCreate>({
    agent_id: null,
    scope: 'memory:read',
    action: 'allow',
    priority: 100,
    // KMV-QA-023: namespace_filter is now included in the form
    namespace_filter: undefined,
  })

  const columns: ColumnDef<PermissionRuleResponse, unknown>[] = [
    { accessorKey: 'priority', header: 'Priority' },
    {
      accessorKey: 'agent_id',
      header: 'Agent',
      cell: ({ getValue }) => {
        const id = getValue() as string | null
        if (!id) return <span className="text-content-tertiary italic">All agents</span>
        const agent = agents.data?.find((a) => a.agent_id === id)
        return agent?.agent_name ?? <code className="text-xs">{id.slice(0, 8)}…</code>
      },
    },
    { accessorKey: 'scope', header: 'Scope' },
    {
      accessorKey: 'action',
      header: 'Action',
      cell: ({ getValue }) => <StatusBadge status={getValue() as string} />,
    },
    {
      accessorKey: 'namespace_filter',
      header: 'Namespace Filter',
      cell: ({ getValue }) => {
        const v = getValue() as string | null
        return v ? (
          <code className="rounded bg-surface-secondary px-1 py-0.5 text-xs">{v}</code>
        ) : (
          <span className="text-content-tertiary">—</span>
        )
      },
    },
    {
      accessorKey: 'is_active',
      header: 'Active',
      cell: ({ getValue }) => (
        <span className={getValue() ? 'text-status-success font-medium' : 'text-content-tertiary'}>
          {getValue() ? 'Yes' : 'No'}
        </span>
      ),
    },
    {
      id: 'actions',
      header: '',
      cell: ({ row }: { row: Row<PermissionRuleResponse> }) => (
        <div className="flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
          {/* KMV-QA-024: Enable/disable toggle */}
          <button
            onClick={() => toggleMut.mutate({ ruleId: row.original.rule_id, isActive: !row.original.is_active })}
            disabled={toggleMut.isPending}
            title={row.original.is_active ? 'Disable rule' : 'Enable rule'}
            className="rounded p-1 text-content-tertiary hover:bg-surface-secondary disabled:opacity-40"
          >
            {row.original.is_active ? (
              <ToggleRight size={16} className="text-status-success" />
            ) : (
              <ToggleLeft size={16} />
            )}
          </button>
          {/* Delete */}
          <button
            onClick={() => setDeleteId(row.original.rule_id)}
            className="rounded p-1 text-content-tertiary hover:bg-red-50 hover:text-status-danger"
            title="Delete rule"
          >
            <Trash2 size={14} />
          </button>
        </div>
      ),
    },
  ]

  // Detect duplicate rules (same agent_id + scope + action + namespace_filter)
  const hasDuplicates = useMemo(() => {
    if (!permissions.data) return false
    const seen = new Set<string>()
    for (const r of permissions.data) {
      const key = `${r.agent_id ?? ''}|${r.scope}|${r.action}|${r.namespace_filter ?? ''}`
      if (seen.has(key)) return true
      seen.add(key)
    }
    return false
  }, [permissions.data])

  return (
    <PageShell>
      {/* Duplicate rule warning */}
      {hasDuplicates && (
        <div className="mb-4 flex items-start gap-3 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3">
          <span className="mt-0.5 shrink-0 text-amber-500 text-base">&#9888;</span>
          <div>
            <p className="text-sm font-medium text-amber-700">Duplicate rules detected</p>
            <p className="text-xs text-amber-600">
              One or more rules share the same agent, scope, action, and namespace filter.
              In a first-match-wins policy engine only the highest-priority (lowest number) rule
              will ever fire — the duplicates are dead weight. Consider removing them.
            </p>
          </div>
        </div>
      )}
      <div className="mb-4 flex items-center justify-between">
        <p className="text-sm text-content-secondary">
          {permissions.data?.length ?? 0} rules (first-match-wins by priority)
        </p>
        <button
          onClick={() => setShowForm(!showForm)}
          className="flex items-center gap-1.5 rounded-lg bg-brand-primary px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700"
        >
          <Plus size={16} /> Add Rule
        </button>
      </div>

      {/* Inline create form — KMV-QA-023: includes namespace_filter field */}
      {showForm && (
        <div className="mb-4 rounded-lg border border-border bg-white p-4">
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
            <div>
              <label className="mb-1 block text-xs font-medium text-content-secondary">Agent</label>
              <select
                value={form.agent_id ?? ''}
                onChange={(e) => setForm((f) => ({ ...f, agent_id: e.target.value || null }))}
                className="w-full rounded border border-border px-2 py-1.5 text-sm"
              >
                <option value="">All agents</option>
                {agents.data?.map((a) => (
                  <option key={a.agent_id} value={a.agent_id}>{a.agent_name}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-content-secondary">Scope</label>
              <select
                value={form.scope}
                onChange={(e) => setForm((f) => ({ ...f, scope: e.target.value }))}
                className="w-full rounded border border-border px-2 py-1.5 text-sm"
              >
                {VALID_SCOPES.map((s) => (
                  <option key={s} value={s}>{s}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-content-secondary">Action</label>
              <select
                value={form.action}
                onChange={(e) => setForm((f) => ({ ...f, action: e.target.value as ValidAction }))}
                className="w-full rounded border border-border px-2 py-1.5 text-sm"
              >
                {VALID_ACTIONS.map((a) => (
                  <option key={a} value={a}>{a}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-content-secondary">Priority</label>
              <input
                type="number"
                min={1}
                max={10000}
                value={form.priority}
                onChange={(e) => setForm((f) => ({ ...f, priority: Number(e.target.value) }))}
                className="w-full rounded border border-border px-2 py-1.5 text-sm"
              />
            </div>
            {/* KMV-QA-023: Namespace filter input */}
            <div className="sm:col-span-2">
              <label className="mb-1 block text-xs font-medium text-content-secondary">
                Namespace Filter{' '}
                <span className="font-normal text-content-tertiary">(optional — leave blank for all namespaces)</span>
              </label>
              <input
                type="text"
                placeholder="e.g. personal, work, finance"
                value={form.namespace_filter ?? ''}
                onChange={(e) =>
                  setForm((f) => ({ ...f, namespace_filter: e.target.value || undefined }))
                }
                className="w-full rounded border border-border px-2 py-1.5 text-sm placeholder:text-content-tertiary"
              />
            </div>
          </div>
          <div className="mt-3 flex justify-end gap-2">
            <button
              onClick={() => setShowForm(false)}
              className="rounded-lg border border-border px-3 py-1.5 text-sm text-content-secondary"
            >
              Cancel
            </button>
            <button
              onClick={() => {
                createMut.mutate(form, { onSuccess: () => setShowForm(false) })
              }}
              disabled={createMut.isPending}
              className="rounded-lg bg-brand-primary px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-700"
            >
              Create
            </button>
          </div>
        </div>
      )}

      {permissions.isLoading ? (
        <LoadingSkeleton lines={8} />
      ) : permissions.data ? (
        <DataTable columns={columns} data={permissions.data} />
      ) : (
        <p className="py-8 text-center text-sm text-content-tertiary">No permission rules found.</p>
      )}

      <ConfirmDialog
        open={deleteId !== null}
        onOpenChange={() => setDeleteId(null)}
        title="Delete Permission Rule"
        description="Are you sure you want to delete this permission rule? This action cannot be undone."
        confirmLabel="Delete"
        variant="danger"
        onConfirm={() => {
          if (deleteId) deleteMut.mutate(deleteId)
        }}
      />
    </PageShell>
  )
}
