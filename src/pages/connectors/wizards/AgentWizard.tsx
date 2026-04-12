import { useState } from 'react'
import { WizardSteps, WizardNav, CodeBlock } from '../ConnectorWizard'
import { Check, Copy, AlertCircle } from 'lucide-react'
import { registerAgent } from '@/api/agents'
import type { AgentRegistrationResponse } from '@/api/types'
import { useQueryClient } from '@tanstack/react-query'

interface Props { onClose: () => void }

const defaultScopes = [
  { scope: 'memory:read', reason: 'Read stored memories' },
  { scope: 'memory:write', reason: 'Store new memories' },
]

export function AgentWizard({ onClose }: Props) {
  const [step, setStep] = useState(0)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [scopes, setScopes] = useState(defaultScopes)
  const [result, setResult] = useState<AgentRegistrationResponse | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const qc = useQueryClient()

  const total = 3

  async function handleRegister() {
    setError('')
    setLoading(true)
    try {
      const resp = await registerAgent({
        agent_name: name,
        agent_description: description,
        declared_scopes: scopes,
      })
      setResult(resp)
      qc.invalidateQueries({ queryKey: ['agents'] })
      setStep(2)
    } catch (err: any) {
      const body = await err?.response?.json?.().catch(() => null)
      setError(body?.detail ?? err?.message ?? 'Registration failed')
    } finally {
      setLoading(false)
    }
  }

  const curlExample = result
    ? `curl -s http://localhost:8100/api/v1/memories \\
  -H "X-API-Key: ${result.api_key}" \\
  -H "Content-Type: application/json" \\
  -d '{"namespace": "shared", "content": "Hello from ${name}"}'`
    : ''

  const pythonExample = result
    ? `import httpx

resp = httpx.post(
    "http://localhost:8100/api/v1/memories",
    headers={"X-API-Key": "${result.api_key}"},
    json={"namespace": "shared", "content": "Hello from ${name}"}
)
print(resp.json())`
    : ''

  if (step === 0) {
    return (
      <>
        <WizardSteps current={0} total={total} />
        <h3 className="text-sm font-semibold text-content-primary mb-3">Agent Details</h3>
        <div className="space-y-3">
          <div>
            <label className="block text-xs font-medium text-content-secondary mb-1">Agent Name</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="my-custom-agent"
              className="w-full rounded-lg border border-border bg-white px-3 py-2 text-sm text-content-primary placeholder:text-content-tertiary focus:border-brand-primary focus:outline-none focus:ring-1 focus:ring-brand-primary"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-content-secondary mb-1">Description</label>
            <input
              type="text"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="What this agent does"
              className="w-full rounded-lg border border-border bg-white px-3 py-2 text-sm text-content-primary placeholder:text-content-tertiary focus:border-brand-primary focus:outline-none focus:ring-1 focus:ring-brand-primary"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-content-secondary mb-1">Scopes</label>
            <div className="space-y-2">
              {['memory:read', 'memory:write', 'memory:delete'].map((scope) => {
                const active = scopes.some((s) => s.scope === scope)
                return (
                  <label key={scope} className="flex items-center gap-2 text-sm text-content-secondary">
                    <input
                      type="checkbox"
                      checked={active}
                      onChange={(e) => {
                        if (e.target.checked) {
                          setScopes([...scopes, { scope, reason: `Agent requires ${scope}` }])
                        } else {
                          setScopes(scopes.filter((s) => s.scope !== scope))
                        }
                      }}
                      className="h-4 w-4 rounded border-border text-brand-primary focus:ring-brand-primary"
                    />
                    <code className="text-xs bg-surface-secondary px-1.5 py-0.5 rounded">{scope}</code>
                  </label>
                )
              })}
            </div>
          </div>
        </div>
        <WizardNav
          step={0}
          total={total}
          onBack={() => {}}
          onNext={() => setStep(1)}
          nextDisabled={!name.trim()}
        />
      </>
    )
  }

  if (step === 1) {
    return (
      <>
        <WizardSteps current={1} total={total} />
        <h3 className="text-sm font-semibold text-content-primary mb-3">Confirm & Register</h3>
        <div className="rounded-lg border border-border bg-surface-secondary p-4 text-sm">
          <div className="flex justify-between py-1">
            <span className="text-content-tertiary">Name</span>
            <span className="font-medium text-content-primary">{name}</span>
          </div>
          <div className="flex justify-between py-1">
            <span className="text-content-tertiary">Description</span>
            <span className="font-medium text-content-primary">{description || '(none)'}</span>
          </div>
          <div className="flex justify-between py-1">
            <span className="text-content-tertiary">Scopes</span>
            <span className="font-medium text-content-primary">{scopes.map((s) => s.scope).join(', ')}</span>
          </div>
        </div>
        {error && (
          <div className="mt-3 flex items-center gap-2 rounded-lg bg-status-danger/10 px-3 py-2 text-sm text-status-danger">
            <AlertCircle size={16} /> {error}
          </div>
        )}
        <WizardNav
          step={1}
          total={total}
          onBack={() => setStep(0)}
          onNext={handleRegister}
          nextLabel={loading ? 'Registering...' : 'Register Agent'}
          nextDisabled={loading}
        />
      </>
    )
  }

  return (
    <>
      <WizardSteps current={2} total={total} />
      <div className="flex flex-col items-center py-2">
        <div className="flex h-14 w-14 items-center justify-center rounded-full bg-status-success/10">
          <Check size={28} className="text-status-success" />
        </div>
        <h3 className="mt-3 text-sm font-semibold text-content-primary">Agent Registered</h3>
      </div>
      {result && (
        <div className="mt-3 space-y-3">
          <div>
            <label className="block text-xs font-medium text-content-secondary mb-1">API Key (save this — shown only once)</label>
            <div className="flex items-center gap-2 rounded-lg border border-status-warning/40 bg-status-warning/5 px-3 py-2">
              <code className="flex-1 break-all text-xs font-mono text-content-primary">{result.api_key}</code>
              <button
                onClick={() => navigator.clipboard.writeText(result.api_key)}
                className="shrink-0 rounded p-1 text-content-tertiary hover:bg-surface-secondary"
              >
                <Copy size={14} />
              </button>
            </div>
          </div>
          <div>
            <label className="block text-xs font-medium text-content-secondary mb-1">Agent ID</label>
            <code className="text-xs text-content-tertiary">{result.agent_id}</code>
          </div>
          <CodeBlock label="Test with curl:" code={curlExample} />
          <CodeBlock label="Test with Python:" code={pythonExample} />
        </div>
      )}
      <WizardNav step={2} total={total} onBack={() => setStep(1)} onNext={onClose} nextLabel="Done" />
    </>
  )
}
