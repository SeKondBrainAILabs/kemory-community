import { useState } from 'react'
import { WizardSteps, WizardNav, CodeBlock } from '../ConnectorWizard'
import { Check, AlertCircle, Loader2 } from 'lucide-react'

interface Props { onClose: () => void }

export function CognitionBridgeWizard({ onClose }: Props) {
  const [step, setStep] = useState(0)
  const [url, setUrl] = useState('http://localhost:3002')
  const [token, setToken] = useState('')
  const [orgId, setOrgId] = useState('')
  const [testResult, setTestResult] = useState<'idle' | 'loading' | 'ok' | 'error'>('idle')
  const [testError, setTestError] = useState('')

  const total = 3

  const envConfig = `# Add to .env or docker-compose environment:
COGNITION_OS_URL=${url}
COGNITION_OS_AUTH_TOKEN=${token || '<your-service-auth-secret>'}
COGNITION_OS_ORG_ID=${orgId || '<your-org-id>'}`

  async function testConnection() {
    setTestResult('loading')
    setTestError('')
    try {
      const resp = await fetch(`${url}/health`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        signal: AbortSignal.timeout(5000),
      })
      if (resp.ok) {
        setTestResult('ok')
      } else {
        setTestResult('error')
        setTestError(`HTTP ${resp.status}: ${resp.statusText}`)
      }
    } catch (err: any) {
      setTestResult('error')
      setTestError(err?.message ?? 'Connection failed')
    }
  }

  if (step === 0) {
    return (
      <>
        <WizardSteps current={0} total={total} />
        <h3 className="text-sm font-semibold text-content-primary mb-3">Cognition OS Connection</h3>
        <p className="text-xs text-content-secondary mb-4">
          The Cognition OS bridge publishes memory events and enriched entities to the SeKondBrain concept graph. Memories become searchable via graph traversal and semantic vector search.
        </p>
        <div className="space-y-3">
          <div>
            <label className="block text-xs font-medium text-content-secondary mb-1">Cognition OS URL</label>
            <input
              type="text"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="http://localhost:3002"
              className="w-full rounded-lg border border-border bg-white px-3 py-2 text-sm text-content-primary focus:border-brand-primary focus:outline-none focus:ring-1 focus:ring-brand-primary"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-content-secondary mb-1">Service Auth Token</label>
            <input
              type="password"
              value={token}
              onChange={(e) => setToken(e.target.value)}
              placeholder="SERVICE_AUTH_SECRET from Cognition OS"
              className="w-full rounded-lg border border-border bg-white px-3 py-2 text-sm text-content-primary focus:border-brand-primary focus:outline-none focus:ring-1 focus:ring-brand-primary"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-content-secondary mb-1">Organisation ID</label>
            <input
              type="text"
              value={orgId}
              onChange={(e) => setOrgId(e.target.value)}
              placeholder="org-abc-123"
              className="w-full rounded-lg border border-border bg-white px-3 py-2 text-sm text-content-primary focus:border-brand-primary focus:outline-none focus:ring-1 focus:ring-brand-primary"
            />
          </div>
        </div>
        <WizardNav step={0} total={total} onBack={() => {}} onNext={() => setStep(1)} nextDisabled={!url.trim()} />
      </>
    )
  }

  if (step === 1) {
    return (
      <>
        <WizardSteps current={1} total={total} />
        <h3 className="text-sm font-semibold text-content-primary mb-3">Test Connection</h3>
        <div className="rounded-lg border border-border p-4">
          <div className="flex items-center justify-between">
            <span className="text-sm text-content-secondary">Endpoint: {url}/health</span>
            <button
              onClick={testConnection}
              disabled={testResult === 'loading'}
              className="rounded-lg bg-brand-primary px-4 py-1.5 text-xs font-medium text-white hover:bg-brand-primary/90 disabled:opacity-50"
            >
              {testResult === 'loading' ? (
                <><Loader2 size={14} className="mr-1 inline-block animate-spin" />Testing...</>
              ) : 'Test'}
            </button>
          </div>
          {testResult === 'ok' && (
            <div className="mt-3 flex items-center gap-2 text-sm text-status-success">
              <Check size={16} /> Connected successfully
            </div>
          )}
          {testResult === 'error' && (
            <div className="mt-3 flex items-center gap-2 text-sm text-status-danger">
              <AlertCircle size={16} /> {testError}
            </div>
          )}
        </div>
        <CodeBlock label="Environment configuration:" code={envConfig} />
        <p className="mt-3 text-xs text-content-tertiary">
          Add these variables to your backend environment and restart kemory-api to activate the bridge.
        </p>
        <WizardNav step={1} total={total} onBack={() => setStep(0)} onNext={() => setStep(2)} />
      </>
    )
  }

  return (
    <>
      <WizardSteps current={2} total={total} />
      <div className="flex flex-col items-center py-4">
        <div className="flex h-14 w-14 items-center justify-center rounded-full bg-status-success/10">
          <Check size={28} className="text-status-success" />
        </div>
        <h3 className="mt-3 text-sm font-semibold text-content-primary">Bridge Configured</h3>
        <p className="mt-2 text-center text-xs text-content-secondary max-w-xs">
          When enabled, the bridge will:
        </p>
        <ul className="mt-2 space-y-1 text-xs text-content-secondary">
          <li>Publish new memories as graph nodes (write-through)</li>
          <li>Upsert enriched entities to the shared concept pool</li>
          <li>Expand recall queries via graph + vector search</li>
        </ul>
      </div>
      <WizardNav step={2} total={total} onBack={() => setStep(1)} onNext={onClose} nextLabel="Done" />
    </>
  )
}
