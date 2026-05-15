import { useState } from 'react'
import { WizardSteps, WizardNav, CodeBlock } from '../ConnectorWizard'
import { Check, Terminal, AlertCircle } from 'lucide-react'
import { registerAgent } from '@/api/agents'
import { useQueryClient } from '@tanstack/react-query'
import { PROMPT_CLAUDE_CODE } from '@/lib/connectorSystemPrompts'
import { useAgents } from '@/hooks/useAgents'
import { defaultApiUrl, defaultScriptPath } from '@/lib/connectorDefaults'

interface Props { onClose: () => void }

const AGENT_NAME = 'claude-code-agent'
const AGENT_DESC = 'Claude Code persistent memory MCP agent'

export function ClaudeCodeWizard({ onClose }: Props) {
  const [step, setStep] = useState(0)
  const [serverPath, setServerPath] = useState(defaultScriptPath)
  const [apiUrl, setApiUrl] = useState(defaultApiUrl)
  const [apiKey, setApiKey] = useState('')
  const [registering, setRegistering] = useState(false)
  const [regError, setRegError] = useState('')
  const qc = useQueryClient()
  const agents = useAgents()
  const existingAgent = (agents.data ?? []).find(a => a.agent_name === AGENT_NAME && a.status !== 'revoked')

  function buildConfig(key: string) {
    return JSON.stringify(
      {
        mcpServers: {
          'kemory': {
            command: 'python3',
            args: [serverPath],
            env: { KEMORY_API_URL: apiUrl, KEMORY_API_KEY: key },
          },
        },
      },
      null,
      2,
    )
  }

  async function handleRegister() {
    setRegistering(true)
    setRegError('')
    try {
      const resp = await registerAgent({
        agent_name: AGENT_NAME,
        agent_description: AGENT_DESC,
        declared_scopes: [
          { scope: 'memory:read', reason: 'Claude needs to recall user memories' },
          { scope: 'memory:write', reason: 'Claude needs to store user memories' },
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
      setRegError('Agent already registered. Enter the existing API key or re-register from the Agents page.')
      setStep(2)
    } else {
      handleRegister()
    }
  }

  const total = 3

  // Step 0: Prerequisites
  if (step === 0) {
    return (
      <>
        <WizardSteps current={0} total={total} />
        <h3 className="text-sm font-semibold text-content-primary mb-3">Prerequisites</h3>
        <ul className="space-y-3 text-sm text-content-secondary">
          <li className="flex items-start gap-2">
            <Check size={16} className="mt-0.5 shrink-0 text-status-success" />
            Python 3.10+ installed
          </li>
          <li className="flex items-start gap-2">
            <Check size={16} className="mt-0.5 shrink-0 text-status-success" />
            S9N Memory Vault API running
          </li>
          <li className="flex items-start gap-2">
            <Terminal size={16} className="mt-0.5 shrink-0 text-brand-primary" />
            MCP server script: <code className="text-xs bg-surface-secondary px-1.5 py-0.5 rounded">scripts/kemory_mcp_server.py</code>
          </li>
        </ul>
        {existingAgent && (
          <div className="mt-4 flex items-center gap-2 rounded-lg bg-status-success/10 px-3 py-2 text-xs text-status-success">
            <Check size={14} /> Agent &quot;{AGENT_NAME}&quot; already registered ({existingAgent.status})
          </div>
        )}
        <WizardNav step={0} total={total} onBack={() => {}} onNext={() => setStep(1)} />
      </>
    )
  }

  // Step 1: Configure paths
  if (step === 1) {
    return (
      <>
        <WizardSteps current={1} total={total} />
        <h3 className="text-sm font-semibold text-content-primary mb-3">Configuration</h3>
        <div className="space-y-3">
          <div>
            <label className="block text-xs font-medium text-content-secondary mb-1">MCP Server Script Path</label>
            <input type="text" value={serverPath} onChange={(e) => setServerPath(e.target.value)}
              className="w-full rounded-lg border border-border bg-white px-3 py-2 text-sm text-content-primary focus:border-brand-primary focus:outline-none focus:ring-1 focus:ring-brand-primary" />
          </div>
          <div>
            <label className="block text-xs font-medium text-content-secondary mb-1">API URL</label>
            <input type="text" value={apiUrl} onChange={(e) => setApiUrl(e.target.value)}
              className="w-full rounded-lg border border-border bg-white px-3 py-2 text-sm text-content-primary focus:border-brand-primary focus:outline-none focus:ring-1 focus:ring-brand-primary" />
          </div>
          {existingAgent ? (
            <div>
              <label className="block text-xs font-medium text-content-secondary mb-1">API Key (from previous registration)</label>
              <input type="text" value={apiKey} onChange={(e) => setApiKey(e.target.value)} placeholder="Paste your existing API key"
                className="w-full rounded-lg border border-border bg-white px-3 py-2 text-sm font-mono text-content-primary placeholder:text-content-tertiary focus:border-brand-primary focus:outline-none focus:ring-1 focus:ring-brand-primary" />
              <p className="mt-1 text-xs text-content-tertiary">Agent already registered. Enter the API key issued at registration.</p>
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
          step={1} total={total} onBack={() => setStep(0)} onNext={handleNextFromConfig}
          nextLabel={registering ? 'Registering...' : existingAgent ? 'Next' : 'Register & Generate Key'}
          nextDisabled={registering}
        />
      </>
    )
  }

  // Step 2: Output — config + CLAUDE.md prompt
  const claudeMdSnippet = PROMPT_CLAUDE_CODE

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
          <label className="block text-xs font-medium text-status-warning mb-1">API Key (save this — shown only once)</label>
          <div className="flex items-center gap-2 rounded-lg border border-status-warning/40 bg-status-warning/5 px-3 py-2">
            <code className="flex-1 break-all text-xs font-mono text-content-primary">{apiKey}</code>
          </div>
        </div>
      )}

      <div className="space-y-3 max-h-64 overflow-y-auto">
        <CodeBlock label="1. Add to .claude/settings.json:" code={buildConfig(apiKey)} />
        <CodeBlock label="2. Add to CLAUDE.md (memory instructions):" code={claudeMdSnippet} />
      </div>

      <p className="mt-1.5 text-xs text-content-tertiary">
        Replace <code className="rounded bg-surface-secondary px-1">{'{{PROJECT_SLUG}}'}</code> with your project name.
      </p>
      <p className="mt-3 text-center text-xs text-content-tertiary">
        Restart Claude Code after adding the MCP config. 14 MCP tools available including s9nmem_get_user_context for cross-namespace session bootstrap.
      </p>
      <WizardNav step={2} total={total} onBack={() => setStep(1)} onNext={onClose} nextLabel="Done" />
    </>
  )
}
