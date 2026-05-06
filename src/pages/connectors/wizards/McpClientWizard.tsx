import { useState, useMemo } from 'react'
import { WizardSteps, WizardNav, CodeBlock } from '../ConnectorWizard'
import { Check, AlertCircle } from 'lucide-react'
import { registerAgent } from '@/api/agents'
import { useQueryClient } from '@tanstack/react-query'
import { useAgents } from '@/hooks/useAgents'
import { defaultApiUrl, defaultScriptPath } from '@/lib/connectorDefaults'

/**
 * Generic MCP client wizard — parameterised by a descriptor so every new
 * client (Cursor, Windsurf, Cline, Codex, Gemini CLI, a user-built custom
 * client) can be onboarded without forking a new Wizard component.
 *
 * Every MCP client accepts the same `mcpServers` JSON shape; only the
 * location of the config file and the restart UX differ. We surface those
 * differences via `configPaths` and `notes`.
 */
export interface McpClientDescriptor {
  /** Stable id — must match the ConnectorId in ConnectorsPage. */
  id: string
  /** Display name, e.g. "Cursor". */
  name: string
  /** Agent name registered in the Memory Vault. */
  agentName: string
  /** Description stored on the agent when registering. */
  agentDescription: string
  /**
   * Config file locations per OS. Each entry is the absolute path the user
   * should open to paste the mcpServers JSON, and a short label identifying
   * the file ("settings.json", "mcp.json", ...).
   */
  configPaths: Array<{ os: 'macOS' | 'Linux' | 'Windows'; path: string; label: string }>
  /** How the top-level key in mcpServers should be called (usually "kemory"). */
  serverKey?: string
  /** Free-form notes shown on the final screen (restart instructions, etc.). */
  notes?: string[]
  /** Optional name of a pre-packaged `.mcp.json` file to mention. */
  projectScopedHint?: string
}

interface Props {
  descriptor: McpClientDescriptor
  onClose: () => void
}

export function McpClientWizard({ descriptor, onClose }: Props) {
  const [step, setStep] = useState(0)
  const [apiUrl, setApiUrl] = useState(defaultApiUrl)
  const [serverPath, setServerPath] = useState(defaultScriptPath)
  const [apiKey, setApiKey] = useState('')
  const [registering, setRegistering] = useState(false)
  const [regError, setRegError] = useState('')
  const qc = useQueryClient()
  const agents = useAgents()
  const existingAgent = (agents.data ?? []).find((a) => a.agent_name === descriptor.agentName)

  const serverKey = descriptor.serverKey ?? 'kemory'
  const total = 3

  const configJson = useMemo(
    () =>
      JSON.stringify(
        {
          mcpServers: {
            [serverKey]: {
              command: 'python3',
              args: [serverPath],
              env: {
                S9NMV_API_URL: apiUrl,
                S9NMV_API_KEY: apiKey || '<YOUR_API_KEY>',
              },
            },
          },
        },
        null,
        2,
      ),
    [serverKey, serverPath, apiUrl, apiKey],
  )

  async function handleRegister() {
    setRegistering(true)
    setRegError('')
    try {
      const resp = await registerAgent({
        agent_name: descriptor.agentName,
        agent_description: descriptor.agentDescription,
        declared_scopes: [
          { scope: 'memory:read', reason: `${descriptor.name} needs to recall user memories` },
          { scope: 'memory:write', reason: `${descriptor.name} needs to store user memories` },
        ],
      })
      setApiKey(resp.api_key)
      qc.invalidateQueries({ queryKey: ['agents'] })
      setStep(2)
    } catch (err: any) {
      const body = await err?.response?.json?.().catch(() => null)
      setRegError(body?.detail ?? err?.message ?? 'Registration failed')
    } finally {
      setRegistering(false)
    }
  }

  function handleNextFromConfig() {
    if (existingAgent && apiKey) {
      setStep(2)
    } else if (existingAgent && !apiKey) {
      setRegError(
        'Agent already registered. Paste the API key you saved at registration, or revoke and re-register from the Agents page.',
      )
    } else {
      handleRegister()
    }
  }

  // Step 0 — Prerequisites
  if (step === 0) {
    return (
      <>
        <WizardSteps current={0} total={total} />
        <h3 className="mb-3 text-sm font-semibold text-content-primary">Prerequisites</h3>
        <ul className="space-y-3 text-sm text-content-secondary">
          <li className="flex items-start gap-2">
            <Check size={16} className="mt-0.5 shrink-0 text-status-success" />
            Python 3.10+ on your machine (runs the MCP stdio bridge)
          </li>
          <li className="flex items-start gap-2">
            <Check size={16} className="mt-0.5 shrink-0 text-status-success" />
            {descriptor.name} installed and up-to-date with MCP support
          </li>
          <li className="flex items-start gap-2">
            <Check size={16} className="mt-0.5 shrink-0 text-status-success" />
            Kemory API reachable at <code className="rounded bg-surface-secondary px-1.5 py-0.5 text-xs">{apiUrl}</code>
          </li>
        </ul>

        <div className="mt-5">
          <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-content-tertiary">
            Where this client stores MCP config
          </h4>
          <div className="space-y-1.5 text-xs text-content-secondary">
            {descriptor.configPaths.map((p) => (
              <div key={`${p.os}:${p.path}`} className="flex items-baseline gap-2">
                <span className="w-16 shrink-0 font-medium text-content-primary">{p.os}</span>
                <code className="break-all rounded bg-surface-secondary px-1.5 py-0.5">{p.path}</code>
              </div>
            ))}
          </div>
          {descriptor.projectScopedHint && (
            <p className="mt-2 text-xs text-content-tertiary">{descriptor.projectScopedHint}</p>
          )}
        </div>

        {existingAgent && (
          <div className="mt-4 flex items-center gap-2 rounded-lg bg-status-success/10 px-3 py-2 text-xs text-status-success">
            <Check size={14} /> Agent &quot;{descriptor.agentName}&quot; already registered ({existingAgent.status})
          </div>
        )}

        <WizardNav step={0} total={total} onBack={() => {}} onNext={() => setStep(1)} />
      </>
    )
  }

  // Step 1 — Configuration inputs
  if (step === 1) {
    return (
      <>
        <WizardSteps current={1} total={total} />
        <h3 className="mb-3 text-sm font-semibold text-content-primary">Configuration</h3>
        <div className="space-y-3">
          <div>
            <label className="mb-1 block text-xs font-medium text-content-secondary">MCP server script path</label>
            <input
              type="text"
              value={serverPath}
              onChange={(e) => setServerPath(e.target.value)}
              className="w-full rounded-lg border border-border bg-white px-3 py-2 text-sm text-content-primary focus:border-brand-primary focus:outline-none focus:ring-1 focus:ring-brand-primary"
            />
            <p className="mt-1 text-xs text-content-tertiary">
              Absolute path to <code>scripts/kemory_mcp_server.py</code> in the Kemory repo.
            </p>
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-content-secondary">API URL</label>
            <input
              type="text"
              value={apiUrl}
              onChange={(e) => setApiUrl(e.target.value)}
              className="w-full rounded-lg border border-border bg-white px-3 py-2 text-sm text-content-primary focus:border-brand-primary focus:outline-none focus:ring-1 focus:ring-brand-primary"
            />
          </div>
          {existingAgent ? (
            <div>
              <label className="mb-1 block text-xs font-medium text-content-secondary">
                API Key (from previous registration)
              </label>
              <input
                type="text"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder="Paste your existing API key"
                className="w-full rounded-lg border border-border bg-white px-3 py-2 font-mono text-sm text-content-primary placeholder:text-content-tertiary focus:border-brand-primary focus:outline-none focus:ring-1 focus:ring-brand-primary"
              />
              <p className="mt-1 text-xs text-content-tertiary">
                Agent already registered. Enter the API key issued at registration.
              </p>
            </div>
          ) : (
            <p className="text-xs text-content-tertiary">
              An API key will be auto-generated when you click Next.
            </p>
          )}
        </div>
        {regError && (
          <div className="mt-3 flex items-center gap-2 rounded-lg bg-status-danger/10 px-3 py-2 text-xs text-status-danger">
            <AlertCircle size={14} /> {regError}
          </div>
        )}
        <WizardNav
          step={1}
          total={total}
          onBack={() => setStep(0)}
          onNext={handleNextFromConfig}
          nextLabel={registering ? 'Registering...' : existingAgent ? 'Next' : 'Register & Generate Key'}
          nextDisabled={registering}
        />
      </>
    )
  }

  // Step 2 — Output
  return (
    <>
      <WizardSteps current={2} total={total} />
      <div className="flex flex-col items-center py-3">
        <div className="flex h-14 w-14 items-center justify-center rounded-full bg-status-success/10">
          <Check size={28} className="text-status-success" />
        </div>
        <h3 className="mt-3 text-sm font-semibold text-content-primary">
          {apiKey ? 'Agent Registered' : 'Configuration Ready'}
        </h3>
      </div>

      {apiKey && (
        <div className="mb-3">
          <label className="mb-1 block text-xs font-medium text-status-warning">
            API Key (save this — shown only once)
          </label>
          <div className="flex items-center gap-2 rounded-lg border border-status-warning/40 bg-status-warning/5 px-3 py-2">
            <code className="flex-1 break-all font-mono text-xs text-content-primary">{apiKey}</code>
          </div>
        </div>
      )}

      <div className="max-h-64 space-y-3 overflow-y-auto">
        <div className="text-xs text-content-secondary">
          <div className="mb-1 font-medium text-content-primary">1. Open your MCP config file</div>
          <ul className="ml-4 list-disc space-y-0.5">
            {descriptor.configPaths.map((p) => (
              <li key={`${p.os}:${p.path}`}>
                <span className="font-medium">{p.os}:</span>{' '}
                <code className="break-all rounded bg-surface-secondary px-1 text-[11px]">{p.path}</code>
              </li>
            ))}
          </ul>
        </div>
        <CodeBlock label="2. Paste or merge this into the file:" code={configJson} />
        {descriptor.notes && descriptor.notes.length > 0 && (
          <ul className="mt-2 space-y-1 text-xs text-content-tertiary">
            {descriptor.notes.map((n, i) => (
              <li key={i}>• {n}</li>
            ))}
          </ul>
        )}
      </div>

      <p className="mt-3 text-center text-xs text-content-tertiary">
        Restart {descriptor.name} after saving the config. 6 tools:
        s9nmem_store_memory, s9nmem_recall_memory, s9nmem_delete_memory,
        s9nmem_check_access, s9nmem_list_namespaces, s9nmem_get_context.
      </p>
      <WizardNav step={2} total={total} onBack={() => setStep(1)} onNext={onClose} nextLabel="Done" />
    </>
  )
}
