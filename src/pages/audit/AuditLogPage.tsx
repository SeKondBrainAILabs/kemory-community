/**
 * Memory Vault — Audit Log Page
 *
 * EPIC-002 fixes:
 *   KMV-QA-018: Add date_from / date_to filter inputs
 *   KMV-QA-019: Add CSV export button (client-side, from current page data)
 */
import { useState } from 'react'
import { type ColumnDef } from '@tanstack/react-table'
import { PageShell } from '@/components/layout/PageShell'
import { DataTable } from '@/components/shared/DataTable'
import { StatusBadge } from '@/components/shared/StatusBadge'
import { LoadingSkeleton } from '@/components/shared/LoadingSkeleton'
import { useAuditLogs, useChainVerify } from '@/hooks/useAudit'
import { useAgents } from '@/hooks/useAgents'
import { formatRelativeTime } from '@/lib/utils'
import type { AuditEntry } from '@/api/types'
import { CheckCircle, XCircle, ShieldCheck, Download } from 'lucide-react'

const columns: ColumnDef<AuditEntry, unknown>[] = [
  {
    accessorKey: 'created_at',
    header: 'Time',
    cell: ({ getValue }) => (
      <span className="whitespace-nowrap">{formatRelativeTime(getValue() as string)}</span>
    ),
  },
  { accessorKey: 'action', header: 'Action' },
  { accessorKey: 'resource_type', header: 'Resource' },
  {
    accessorKey: 'outcome',
    header: 'Outcome',
    cell: ({ getValue }) => <StatusBadge status={getValue() as string} />,
  },
  {
    accessorKey: 'agent_id',
    header: 'Agent',
    cell: ({ getValue }) => {
      const v = getValue() as string | null
      return v ? <code className="text-xs">{v.slice(0, 8)}…</code> : '—'
    },
  },
  {
    accessorKey: 'namespace',
    header: 'Namespace',
    cell: ({ getValue }) => (getValue() as string | null) ?? '—',
  },
]

// KMV-QA-019: Client-side CSV export of the current page of audit entries
function exportToCsv(entries: AuditEntry[]) {
  const headers = ['Time', 'Action', 'Resource', 'Outcome', 'Agent ID', 'Namespace']
  const rows = entries.map((e) => [
    e.created_at,
    e.action,
    e.resource_type ?? '',
    e.outcome,
    e.agent_id ?? '',
    e.namespace ?? '',
  ])
  const csv = [headers, ...rows]
    .map((row) => row.map((cell) => `"${String(cell).replace(/"/g, '""')}"`).join(','))
    .join('\n')
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `memory_vault_audit_${new Date().toISOString().slice(0, 10)}.csv`
  link.click()
  URL.revokeObjectURL(url)
}

export function AuditLogPage() {
  const [filters, setFilters] = useState({
    agent_id: '',
    action: '',
    outcome: '',
    date_from: '',
    date_to: '',
    limit: 50,
    offset: 0,
  })

  const { data, isLoading } = useAuditLogs({
    agent_id: filters.agent_id || undefined,
    action: filters.action || undefined,
    outcome: filters.outcome || undefined,
    date_from: filters.date_from || undefined,
    date_to: filters.date_to || undefined,
    limit: filters.limit,
    offset: filters.offset,
  })

  const agents = useAgents()
  const chainVerify = useChainVerify()

  return (
    <PageShell>
      {/* Filters — KMV-QA-018 adds date_from / date_to */}
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <select
          value={filters.agent_id}
          onChange={(e) => setFilters((f) => ({ ...f, agent_id: e.target.value, offset: 0 }))}
          className="rounded-lg border border-border bg-white px-3 py-2 text-sm"
        >
          <option value="">All Agents</option>
          {agents.data?.map((a) => (
            <option key={a.agent_id} value={a.agent_id}>
              {a.agent_name}
            </option>
          ))}
        </select>

        <select
          value={filters.action}
          onChange={(e) => setFilters((f) => ({ ...f, action: e.target.value, offset: 0 }))}
          className="rounded-lg border border-border bg-white px-3 py-2 text-sm"
        >
          <option value="">All Actions</option>
          {['memory:read', 'memory:write', 'memory:delete', 'permission:evaluate'].map((a) => (
            <option key={a} value={a}>{a}</option>
          ))}
        </select>

        <select
          value={filters.outcome}
          onChange={(e) => setFilters((f) => ({ ...f, outcome: e.target.value, offset: 0 }))}
          className="rounded-lg border border-border bg-white px-3 py-2 text-sm"
        >
          <option value="">All Outcomes</option>
          {['success', 'denied', 'error'].map((o) => (
            <option key={o} value={o}>{o}</option>
          ))}
        </select>

        {/* Date range — KMV-QA-018 */}
        <div className="flex items-center gap-2">
          <label className="text-xs text-content-tertiary">From</label>
          <input
            type="date"
            value={filters.date_from}
            onChange={(e) => setFilters((f) => ({ ...f, date_from: e.target.value, offset: 0 }))}
            className="rounded-lg border border-border bg-white px-3 py-2 text-sm focus:border-brand-primary focus:outline-none"
          />
          <label className="text-xs text-content-tertiary">To</label>
          <input
            type="date"
            value={filters.date_to}
            onChange={(e) => setFilters((f) => ({ ...f, date_to: e.target.value, offset: 0 }))}
            className="rounded-lg border border-border bg-white px-3 py-2 text-sm focus:border-brand-primary focus:outline-none"
          />
        </div>

        {/* CSV Export — KMV-QA-019 */}
        <button
          onClick={() => data?.items && exportToCsv(data.items)}
          disabled={!data?.items?.length}
          className="flex items-center gap-1.5 rounded-lg border border-border bg-white px-3 py-2 text-sm font-medium text-content-secondary hover:bg-surface-secondary disabled:opacity-40"
          title="Export current page to CSV"
        >
          <Download size={15} />
          Export CSV
        </button>

        <button
          onClick={() => chainVerify.refetch()}
          disabled={chainVerify.isFetching}
          className="flex items-center gap-1.5 rounded-lg border border-border bg-white px-3 py-2 text-sm font-medium text-content-secondary hover:bg-surface-secondary"
        >
          <ShieldCheck size={16} />
          Verify Chain
        </button>
      </div>

      {/* Chain verify result */}
      {chainVerify.data && (
        <div className="mb-4 flex items-center gap-2 rounded-lg border border-border bg-white px-4 py-3">
          {chainVerify.data.errors.length === 0 ? (
            <>
              <CheckCircle size={16} className="text-status-success" />
              <span className="text-sm text-status-success">
                Chain integrity verified ({chainVerify.data.verified} entries)
              </span>
            </>
          ) : (
            <>
              <XCircle size={16} className="text-status-danger" />
              <span className="text-sm text-status-danger">
                Chain broken: {chainVerify.data.errors.length} errors
              </span>
            </>
          )}
        </div>
      )}

      {isLoading ? (
        <LoadingSkeleton lines={10} />
      ) : data ? (
        <>
          <DataTable columns={columns} data={data.items} />
          {/* Pagination */}
          <div className="mt-4 flex items-center justify-between text-sm text-content-secondary">
            <span>
              Showing {data.offset + 1}–{Math.min(data.offset + data.limit, data.total)} of{' '}
              {data.total}
            </span>
            <div className="flex gap-2">
              <button
                disabled={data.offset === 0}
                onClick={() =>
                  setFilters((f) => ({ ...f, offset: Math.max(0, f.offset - f.limit) }))
                }
                className="rounded border border-border px-3 py-1 hover:bg-surface-secondary disabled:opacity-50"
              >
                Previous
              </button>
              <button
                disabled={data.offset + data.limit >= data.total}
                onClick={() => setFilters((f) => ({ ...f, offset: f.offset + f.limit }))}
                className="rounded border border-border px-3 py-1 hover:bg-surface-secondary disabled:opacity-50"
              >
                Next
              </button>
            </div>
          </div>
        </>
      ) : (
        <div className="py-12 text-center text-sm text-content-tertiary">
          No audit log entries found for the selected filters.
        </div>
      )}
    </PageShell>
  )
}
