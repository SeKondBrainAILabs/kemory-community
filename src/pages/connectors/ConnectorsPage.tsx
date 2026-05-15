import { useState } from 'react'
import { PageShell } from '@/components/layout/PageShell'
import { useAgents, useAgentAction, useDeleteAgent } from '@/hooks/useAgents'
import { StatusBadge } from '@/components/shared/StatusBadge'
import { cn } from '@/lib/utils'
import {
  Terminal,
  Monitor,
  Bot,
  Brain,
  Webhook,
  Plug,
  Check,
  AlertCircle,
  Pause,
  Ban,
  Trash2,
  Play,
  Code2,
  Wind,
  SquareTerminal,
  Sparkles,
  Cpu,
  Puzzle,
} from 'lucide-react'
import { ConnectorWizard } from './ConnectorWizard'
import { QuickConnectPanel } from './QuickConnectPanel'

export type ConnectorId =
  | 'claude-code'
  | 'claude-desktop'
  | 'cursor'
  | 'windsurf'
  | 'cline'
  | 'codex'
  | 'gemini-cli'
  | 'ollama'
  | 'custom-mcp'
  | 'custom-agent'
  | 'cognition-os'
  | 'webhook'

interface ConnectorDef {
  id: ConnectorId
  name: string
  description: string
  category: 'MCP Clients' | 'Agents' | 'Bridges'
  icon: typeof Terminal
  matchAgent?: string // agent_name to check for "connected" status
}

const connectors: ConnectorDef[] = [
  {
    id: 'claude-code',
    name: 'Claude Code',
    description: 'MCP integration for Claude Code CLI and IDE extensions',
    category: 'MCP Clients',
    icon: Terminal,
    matchAgent: 'claude-code-agent',
  },
  {
    id: 'claude-desktop',
    name: 'Claude Desktop',
    description: 'MCP integration for the Claude Desktop app',
    category: 'MCP Clients',
    icon: Monitor,
    matchAgent: 'claude-desktop-agent',
  },
  {
    id: 'cursor',
    name: 'Cursor',
    description: 'AI-first IDE — persistent memory across coding sessions',
    category: 'MCP Clients',
    icon: Code2,
    matchAgent: 'cursor-agent',
  },
  {
    id: 'windsurf',
    name: 'Windsurf',
    description: 'Codeium Windsurf — MCP memory for Cascade agents',
    category: 'MCP Clients',
    icon: Wind,
    matchAgent: 'windsurf-agent',
  },
  {
    id: 'cline',
    name: 'Cline',
    description: 'Autonomous VS Code agent — MCP memory integration',
    category: 'MCP Clients',
    icon: SquareTerminal,
    matchAgent: 'cline-agent',
  },
  {
    id: 'codex',
    name: 'ChatGPT / Codex CLI',
    description: 'OpenAI Codex CLI — memory bridge via MCP',
    category: 'MCP Clients',
    icon: Sparkles,
    matchAgent: 'codex-agent',
  },
  {
    id: 'gemini-cli',
    name: 'Gemini CLI',
    description: 'Google Gemini CLI — MCP memory integration',
    category: 'MCP Clients',
    icon: Sparkles,
    matchAgent: 'gemini-cli-agent',
  },
  {
    id: 'ollama',
    name: 'Ollama',
    description: 'Local Ollama runtime with MCP-aware front-end',
    category: 'MCP Clients',
    icon: Cpu,
    matchAgent: 'ollama-agent',
  },
  {
    id: 'custom-mcp',
    name: 'Custom MCP Client',
    description: 'Any MCP-compliant client — generic setup instructions',
    category: 'MCP Clients',
    icon: Puzzle,
    matchAgent: 'custom-mcp-agent',
  },
  {
    id: 'custom-agent',
    name: 'Custom Agent',
    description: 'Register a new agent with API key authentication',
    category: 'Agents',
    icon: Bot,
  },
  {
    id: 'cognition-os',
    name: 'Cognition OS',
    description: 'Bridge to the SeKondBrain concept graph',
    category: 'Bridges',
    icon: Brain,
  },
  {
    id: 'webhook',
    name: 'Webhook',
    description: 'Send memory events to an external URL',
    category: 'Bridges',
    icon: Webhook,
  },
]

const categories = ['MCP Clients', 'Agents', 'Bridges'] as const

export function ConnectorsPage() {
  const [activeWizard, setActiveWizard] = useState<ConnectorId | null>(null)
  const agents = useAgents()
  const agentAction = useAgentAction()
  const deleteAgent = useDeleteAgent()

  const agentNames = new Set(
    (agents.data ?? []).filter((a) => a.status === 'active').map((a) => a.agent_name),
  )

  function isConnected(c: ConnectorDef): boolean {
    if (c.matchAgent) return agentNames.has(c.matchAgent)
    return false
  }

  function getAgentForConnector(c: ConnectorDef) {
    if (!c.matchAgent) return null
    return (agents.data ?? []).find((a) => a.agent_name === c.matchAgent) ?? null
  }

  return (
    <PageShell>
      <div className="mb-6">
        <p className="text-sm text-content-secondary">
          Connect external systems to Kemory. Use Quick connect for any modern AI — or pick a specific
          client below for the step‑by‑step wizard.
        </p>
      </div>

      <QuickConnectPanel />

      {categories.map((cat) => {
        const items = connectors.filter((c) => c.category === cat)
        return (
          <div key={cat} className="mb-8">
            <h2 className="mb-3 text-sm font-semibold text-content-primary">{cat}</h2>
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {items.map((c) => {
                const connected = isConnected(c)
                const agent = getAgentForConnector(c)
                const Icon = c.icon
                return (
                  <div
                    key={c.id}
                    className="group rounded-xl border border-border bg-white p-5 shadow-sm transition-shadow hover:shadow-md"
                  >
                    <div className="flex items-start justify-between">
                      <div className="flex items-center gap-3">
                        <div
                          className={cn(
                            'flex h-10 w-10 items-center justify-center rounded-lg',
                            connected
                              ? 'bg-status-success/10 text-status-success'
                              : 'bg-surface-secondary text-content-tertiary',
                          )}
                        >
                          <Icon size={20} />
                        </div>
                        <div>
                          <h3 className="text-sm font-semibold text-content-primary">{c.name}</h3>
                          <p className="text-xs text-content-tertiary">{c.category}</p>
                        </div>
                      </div>
                      {connected ? (
                        <span className="flex items-center gap-1 rounded-full bg-status-success/10 px-2 py-0.5 text-xs font-medium text-status-success">
                          <Check size={12} /> Connected
                        </span>
                      ) : (
                        <span className="flex items-center gap-1 rounded-full bg-surface-secondary px-2 py-0.5 text-xs font-medium text-content-tertiary">
                          <AlertCircle size={12} /> Not configured
                        </span>
                      )}
                    </div>

                    <p className="mt-3 text-xs text-content-secondary leading-relaxed">
                      {c.description}
                    </p>

                    {agent && (
                      <div className="mt-2 flex items-center gap-2 text-xs text-content-tertiary">
                        <span>Agent: <span className="font-medium">{agent.agent_name}</span></span>
                        <StatusBadge status={agent.status} />
                      </div>
                    )}

                    <div className="mt-4 flex items-center gap-2">
                      <button
                        onClick={() => setActiveWizard(c.id)}
                        className={cn(
                          'rounded-lg px-4 py-2 text-xs font-medium transition-colors',
                          connected
                            ? 'border border-border bg-white text-content-secondary hover:bg-surface-secondary'
                            : 'bg-brand-primary text-white hover:bg-brand-primary/90',
                        )}
                      >
                        <Plug size={14} className="mr-1.5 inline-block" />
                        {connected ? 'Reconfigure' : 'Set up'}
                      </button>
                      {agent && agent.status === 'active' && (
                        <button
                          onClick={() => agentAction.mutate({ agentId: agent.agent_id, action: 'suspend' })}
                          title="Suspend agent"
                          className="rounded-lg border border-border px-2.5 py-2 text-xs text-content-tertiary hover:bg-status-warning/10 hover:text-status-warning transition-colors"
                        >
                          <Pause size={14} />
                        </button>
                      )}
                      {agent && agent.status === 'suspended' && (
                        <button
                          onClick={() => agentAction.mutate({ agentId: agent.agent_id, action: 'approve' })}
                          title="Re-activate agent"
                          className="rounded-lg border border-border px-2.5 py-2 text-xs text-content-tertiary hover:bg-status-success/10 hover:text-status-success transition-colors"
                        >
                          <Play size={14} />
                        </button>
                      )}
                      {agent && agent.status !== 'revoked' && (
                        <button
                          onClick={() => {
                            if (confirm(`Revoke ${agent.agent_name}? This permanently disables the API key.`))
                              agentAction.mutate({ agentId: agent.agent_id, action: 'revoke' })
                          }}
                          title="Revoke agent"
                          className="rounded-lg border border-border px-2.5 py-2 text-xs text-content-tertiary hover:bg-status-danger/10 hover:text-status-danger transition-colors"
                        >
                          <Ban size={14} />
                        </button>
                      )}
                      {agent && agent.status === 'revoked' && (
                        <button
                          onClick={() => {
                            if (confirm(`Delete ${agent.agent_name}? This cannot be undone.`))
                              deleteAgent.mutate(agent.agent_id)
                          }}
                          title="Delete agent"
                          className="rounded-lg border border-border px-2.5 py-2 text-xs text-content-tertiary hover:bg-status-danger/10 hover:text-status-danger transition-colors"
                        >
                          <Trash2 size={14} />
                        </button>
                      )}
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        )
      })}

      {activeWizard && (
        <ConnectorWizard
          connectorId={activeWizard}
          onClose={() => setActiveWizard(null)}
        />
      )}
    </PageShell>
  )
}
