import { useState } from 'react'
import { WizardSteps, WizardNav, CodeBlock } from '../ConnectorWizard'
import { Check, AlertCircle, Loader2 } from 'lucide-react'

interface Props { onClose: () => void }

const eventTypes = [
  { key: 'memory.created', label: 'Memory Created', description: 'Fires when a new memory is stored' },
  { key: 'memory.updated', label: 'Memory Updated', description: 'Fires when a memory is modified' },
  { key: 'memory.deleted', label: 'Memory Deleted', description: 'Fires when a memory is soft-deleted' },
  { key: 'memory.enriched', label: 'Memory Enriched', description: 'Fires after enrichment pipeline completes' },
]

export function WebhookWizard({ onClose }: Props) {
  const [step, setStep] = useState(0)
  const [url, setUrl] = useState('')
  const [secret, setSecret] = useState('')
  const [selectedEvents, setSelectedEvents] = useState<Set<string>>(new Set(['memory.created']))
  const [testResult, setTestResult] = useState<'idle' | 'loading' | 'ok' | 'error'>('idle')
  const [testError, setTestError] = useState('')

  const total = 3

  const samplePayload = JSON.stringify(
    {
      event: 'memory.created',
      timestamp: new Date().toISOString(),
      data: {
        memory_id: '550e8400-e29b-41d4-a716-446655440000',
        namespace: 'shared',
        content_type: 'text',
        user_id: 'b20a5093-6003-540d-85dc-711ecd216518',
      },
    },
    null,
    2,
  )

  function toggleEvent(key: string) {
    setSelectedEvents((prev) => {
      const next = new Set(prev)
      next.has(key) ? next.delete(key) : next.add(key)
      return next
    })
  }

  async function testWebhook() {
    setTestResult('loading')
    setTestError('')
    try {
      const resp = await fetch(url, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(secret ? { 'X-Webhook-Secret': secret } : {}),
        },
        body: samplePayload,
        signal: AbortSignal.timeout(5000),
      })
      if (resp.ok || resp.status === 204) {
        setTestResult('ok')
      } else {
        setTestResult('error')
        setTestError(`HTTP ${resp.status}: ${resp.statusText}`)
      }
    } catch (err: any) {
      setTestResult('error')
      setTestError(err?.message ?? 'Request failed')
    }
  }

  if (step === 0) {
    return (
      <>
        <WizardSteps current={0} total={total} />
        <h3 className="text-sm font-semibold text-content-primary mb-3">Webhook Configuration</h3>
        <div className="space-y-3">
          <div>
            <label className="block text-xs font-medium text-content-secondary mb-1">Webhook URL</label>
            <input
              type="url"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://your-service.com/webhook/s9nmv"
              className="w-full rounded-lg border border-border bg-white px-3 py-2 text-sm text-content-primary focus:border-brand-primary focus:outline-none focus:ring-1 focus:ring-brand-primary"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-content-secondary mb-1">Secret (optional)</label>
            <input
              type="password"
              value={secret}
              onChange={(e) => setSecret(e.target.value)}
              placeholder="Sent as X-Webhook-Secret header"
              className="w-full rounded-lg border border-border bg-white px-3 py-2 text-sm text-content-primary focus:border-brand-primary focus:outline-none focus:ring-1 focus:ring-brand-primary"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-content-secondary mb-2">Events</label>
            <div className="space-y-2">
              {eventTypes.map((evt) => (
                <label key={evt.key} className="flex items-start gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={selectedEvents.has(evt.key)}
                    onChange={() => toggleEvent(evt.key)}
                    className="mt-0.5 h-4 w-4 rounded border-border text-brand-primary focus:ring-brand-primary"
                  />
                  <div>
                    <span className="font-medium text-content-primary">{evt.label}</span>
                    <p className="text-xs text-content-tertiary">{evt.description}</p>
                  </div>
                </label>
              ))}
            </div>
          </div>
        </div>
        <WizardNav
          step={0}
          total={total}
          onBack={() => {}}
          onNext={() => setStep(1)}
          nextDisabled={!url.trim() || selectedEvents.size === 0}
        />
      </>
    )
  }

  if (step === 1) {
    return (
      <>
        <WizardSteps current={1} total={total} />
        <h3 className="text-sm font-semibold text-content-primary mb-3">Test Webhook</h3>
        <p className="text-xs text-content-secondary mb-3">
          Send a sample payload to verify your endpoint accepts the format.
        </p>
        <CodeBlock label="Sample payload:" code={samplePayload} />
        <div className="mt-4 flex items-center justify-between">
          <span className="text-xs text-content-tertiary">Target: {url}</span>
          <button
            onClick={testWebhook}
            disabled={testResult === 'loading'}
            className="rounded-lg bg-brand-primary px-4 py-1.5 text-xs font-medium text-white hover:bg-brand-primary/90 disabled:opacity-50"
          >
            {testResult === 'loading' ? (
              <><Loader2 size={14} className="mr-1 inline-block animate-spin" />Sending...</>
            ) : 'Send Test'}
          </button>
        </div>
        {testResult === 'ok' && (
          <div className="mt-3 flex items-center gap-2 text-sm text-status-success">
            <Check size={16} /> Webhook received successfully
          </div>
        )}
        {testResult === 'error' && (
          <div className="mt-3 flex items-center gap-2 text-sm text-status-danger">
            <AlertCircle size={16} /> {testError}
          </div>
        )}
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
        <h3 className="mt-3 text-sm font-semibold text-content-primary">Webhook Configured</h3>
        <p className="mt-2 text-center text-xs text-content-secondary max-w-xs">
          Events: {Array.from(selectedEvents).join(', ')}
        </p>
        <p className="mt-1 text-xs text-content-tertiary">
          Note: Webhook delivery requires backend configuration. Add the URL to your backend environment to activate.
        </p>
      </div>
      <WizardNav step={2} total={total} onBack={() => setStep(1)} onNext={onClose} nextLabel="Done" />
    </>
  )
}
