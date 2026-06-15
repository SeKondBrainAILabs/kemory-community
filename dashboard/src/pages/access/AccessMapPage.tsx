/**
 * Memory Vault — Access Map Page
 *
 * EPIC-003 KMV-QA-025: Add scope selector so the matrix can be filtered
 * by any memory scope (memory:read, memory:write, memory:delete, etc.)
 * instead of always showing all memory:* scopes combined.
 * Also adds clickable cells that show the matching rule details in a tooltip.
 */
import { useMemo, useState } from 'react'
import { PageShell } from '@/components/layout/PageShell'
import { LoadingSkeleton } from '@/components/shared/LoadingSkeleton'
import { useAgents } from '@/hooks/useAgents'
import { usePermissions } from '@/hooks/usePermissions'
import { useNamespaces } from '@/hooks/useMemories'
import { VALID_SCOPES } from '@/api/types'
import { cn } from '@/lib/utils'

type AccessType = 'allow' | 'deny' | 'jit' | 'none'

const accessColors: Record<AccessType, string> = {
  allow: 'bg-green-100 text-status-success',
  deny: 'bg-red-100 text-status-danger',
  jit: 'bg-amber-100 text-status-warning',
  none: 'bg-gray-50 text-content-tertiary',
}

interface CellInfo {
  access: AccessType
  ruleId: string | null
  rulePriority: number | null
  namespaceFilter: string | null
}

export function AccessMapPage() {
  const agents = useAgents()
  const permissions = usePermissions()
  const namespaces = useNamespaces()

  // KMV-QA-025: Scope selector — defaults to memory:read
  const [selectedScope, setSelectedScope] = useState<string>('memory:read')
  const [tooltip, setTooltip] = useState<{ agentName: string; ns: string; info: CellInfo } | null>(
    null,
  )

  // Matrix orientation: rows = namespaces, columns = agents.
  // This reads as "who can access this namespace" (one row per resource).
  const matrix = useMemo(() => {
    if (!agents.data || !permissions.data || !namespaces.data) return null

    const agentsList = agents.data
    const rows = namespaces.data.map((n) => {
      const namespace = n.namespace
      const cells: CellInfo[] = agentsList.map((agent) => {
        const rules = permissions.data
          .filter(
            (r) =>
              r.is_active &&
              (r.agent_id === null || r.agent_id === agent.agent_id) &&
              (r.scope === selectedScope || r.scope === '*'),
          )
          .sort((a, b) => a.priority - b.priority)

        for (const rule of rules) {
          if (rule.namespace_filter) {
            const pattern = rule.namespace_filter.replace(/\*/g, '.*')
            if (!new RegExp(`^${pattern}$`).test(namespace)) continue
          }
          return {
            access: rule.action as AccessType,
            ruleId: rule.rule_id,
            rulePriority: rule.priority,
            namespaceFilter: rule.namespace_filter ?? null,
          }
        }
        return { access: 'none' as AccessType, ruleId: null, rulePriority: null, namespaceFilter: null }
      })
      return { namespace, cells }
    })

    return { agents: agentsList, rows }
  }, [agents.data, permissions.data, namespaces.data, selectedScope])

  const isLoading = agents.isLoading || permissions.isLoading || namespaces.isLoading

  return (
    <PageShell>
      <div className="mb-4 flex items-center justify-between">
        <p className="text-sm text-content-secondary">
          Cross-agent access matrix showing which agents can access which namespaces.
          Derived from permission rules (first-match-wins). Click a cell for rule details.
        </p>
        {/* KMV-QA-025: Scope selector */}
        <div className="flex items-center gap-2">
          <label className="text-xs font-medium text-content-secondary">Scope</label>
          <select
            value={selectedScope}
            onChange={(e) => setSelectedScope(e.target.value)}
            className="rounded-lg border border-border bg-white px-3 py-1.5 text-sm focus:border-brand-primary focus:outline-none"
          >
            {VALID_SCOPES.map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
        </div>
      </div>

      {isLoading ? (
        <LoadingSkeleton lines={6} />
      ) : matrix && matrix.rows.length > 0 ? (
        <div className="overflow-auto rounded-lg border border-border bg-white">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-surface-secondary">
                <th className="sticky left-0 z-10 bg-surface-secondary px-4 py-3 text-left text-xs font-medium text-content-secondary">
                  Namespace
                </th>
                {matrix.agents.map((agent) => (
                  <th
                    key={agent.agent_id}
                    className="px-3 py-3 text-center text-xs font-medium text-content-secondary"
                  >
                    <span className="inline-block max-w-[120px] truncate" title={agent.agent_name}>
                      {agent.agent_name}
                    </span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {matrix.rows.map(({ namespace, cells }) => (
                <tr key={namespace} className="border-t border-border hover:bg-surface-secondary/30">
                  <td className="sticky left-0 z-10 bg-white px-4 py-3 font-mono text-xs font-medium text-content-primary">
                    {namespace}
                  </td>
                  {cells.map((info, i) => {
                    const agent = matrix.agents[i]
                    return (
                      <td
                        key={agent?.agent_id ?? i}
                        className="px-3 py-3 text-center"
                        onClick={() => {
                          const agentName = agent?.agent_name ?? ''
                          setTooltip((prev) =>
                            prev?.agentName === agentName && prev?.ns === namespace
                              ? null
                              : { agentName, ns: namespace, info },
                          )
                        }}
                      >
                        <span
                          className={cn(
                            'inline-flex h-7 w-7 cursor-pointer items-center justify-center rounded-md text-xs font-medium capitalize transition-transform hover:scale-110',
                            accessColors[info.access],
                          )}
                          title={`${info.access} — click for details`}
                        >
                          {info.access[0]?.toUpperCase()}
                        </span>
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="rounded-lg border border-border bg-white p-8 text-center text-sm text-content-tertiary">
          No agents, permissions, or namespaces to display
        </div>
      )}

      {/* Cell detail tooltip panel */}
      {tooltip && (
        <div className="mt-4 rounded-lg border border-border bg-white p-4 shadow-sm">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold text-content-primary">Rule Detail</h3>
            <button
              onClick={() => setTooltip(null)}
              className="text-xs text-content-tertiary hover:text-content-primary"
            >
              Close
            </button>
          </div>
          <div className="mt-2 grid grid-cols-2 gap-3 text-xs sm:grid-cols-4">
            <div>
              <span className="text-content-secondary">Agent</span>
              <div className="font-medium text-content-primary">{tooltip.agentName}</div>
            </div>
            <div>
              <span className="text-content-secondary">Namespace</span>
              <div className="font-medium text-content-primary">{tooltip.ns}</div>
            </div>
            <div>
              <span className="text-content-secondary">Access</span>
              <div
                className={cn(
                  'inline-block rounded px-1.5 py-0.5 font-medium capitalize',
                  accessColors[tooltip.info.access],
                )}
              >
                {tooltip.info.access}
              </div>
            </div>
            <div>
              <span className="text-content-secondary">Matched Rule</span>
              <div className="font-medium text-content-primary">
                {tooltip.info.ruleId
                  ? `Priority ${tooltip.info.rulePriority} (${tooltip.info.ruleId.slice(0, 8)}…)`
                  : 'No matching rule'}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Legend */}
      <div className="mt-4 flex gap-4 text-xs text-content-secondary">
        {(['allow', 'deny', 'jit', 'none'] as const).map((t) => (
          <div key={t} className="flex items-center gap-1.5">
            <span className={cn('inline-block h-4 w-4 rounded', accessColors[t])} />
            <span className="capitalize">{t}</span>
          </div>
        ))}
      </div>
    </PageShell>
  )
}
