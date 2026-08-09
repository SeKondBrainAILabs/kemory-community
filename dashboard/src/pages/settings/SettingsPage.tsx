import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  CheckCircle2,
  Cloud,
  Copy,
  Download,
  Eye,
  EyeOff,
  HardDrive,
  KeyRound,
  Save,
  Settings2,
  ShieldCheck,
  Trash2,
  Upload,
} from 'lucide-react'
import {
  exportCommunityBundle,
  getCommunitySettings,
  importCommunityBundle,
  updateCommunitySettings,
  type CommunityRuntimeSettingsUpdate,
} from '@/api/community'
import { getApiKey, setApiKey } from '@/api/client'
import { getConfig } from '@/lib/runtimeConfig'

type CloudProvider = 'openai' | 'voyage' | 'cohere'

const DEFAULT_RUNTIME: CommunityRuntimeSettingsUpdate = {
  embedding_provider: 'fastembed',
  embedding_model: 'BAAI/bge-small-en-v1.5',
  groq_model: 'llama-3.3-70b-versatile',
  artifact_max_bytes: 50 * 1024 * 1024,
  log_level: 'INFO',
}

const PROVIDERS = {
  fastembed: { label: 'FastEmbed (local)', model: 'BAAI/bge-small-en-v1.5' },
  openai: { label: 'OpenAI', model: 'text-embedding-3-small' },
  voyage: { label: 'Voyage', model: 'voyage-3.5' },
  cohere: { label: 'Cohere', model: 'embed-v4.0' },
} as const

export function SettingsPage() {
  const queryClient = useQueryClient()
  const fileRef = useRef<HTMLInputElement | null>(null)
  const [apiKeyDraft, setApiKeyDraft] = useState(getApiKey() ?? getConfig()?.API_KEY ?? '')
  const [showApiKey, setShowApiKey] = useState(false)
  const [groqKeyDraft, setGroqKeyDraft] = useState('')
  const [providerKeyDraft, setProviderKeyDraft] = useState('')
  const [runtime, setRuntime] = useState<CommunityRuntimeSettingsUpdate>(DEFAULT_RUNTIME)
  const [message, setMessage] = useState<string | null>(null)
  const settings = useQuery({ queryKey: ['community-settings'], queryFn: getCommunitySettings })

  useEffect(() => {
    if (!settings.data?.runtime) return
    const {
      groq_configured: _groq,
      openai_configured: _openai,
      voyage_configured: _voyage,
      cohere_configured: _cohere,
      ...values
    } = settings.data.runtime
    setRuntime(values)
  }, [settings.data])

  const updater = useMutation({
    mutationFn: updateCommunitySettings,
    onSuccess: () => {
      setGroqKeyDraft('')
      setProviderKeyDraft('')
      setMessage('Runtime settings saved')
      queryClient.invalidateQueries({ queryKey: ['community-settings'] })
    },
  })
  const importer = useMutation({
    mutationFn: importCommunityBundle,
    onSuccess: (result) => setMessage(`Imported ${result.imported} memories`),
  })

  const provider = runtime.embedding_provider
  const cloudProvider = provider === 'fastembed' ? null : provider
  const providerConfigured = cloudProvider
    ? settings.data?.runtime[`${cloudProvider}_configured`]
    : true
  const providerReady = !cloudProvider || Boolean(providerConfigured) || Boolean(providerKeyDraft.trim())

  async function downloadBackup() {
    const bundle = await exportCommunityBundle()
    const blob = new Blob([JSON.stringify(bundle, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `kemory-community-${new Date().toISOString().slice(0, 10)}.json`
    link.click()
    URL.revokeObjectURL(url)
  }

  async function importBackup(file: File | undefined) {
    if (!file) return
    importer.mutate(JSON.parse(await file.text()))
  }

  function saveApiKey() {
    setApiKey(apiKeyDraft.trim())
    setMessage('Dashboard API key saved')
  }

  function saveRuntime() {
    const secrets: Partial<CommunityRuntimeSettingsUpdate> = {}
    if (groqKeyDraft.trim()) secrets.groq_api_key = groqKeyDraft.trim()
    if (cloudProvider && providerKeyDraft.trim()) {
      secrets[`${cloudProvider}_api_key`] = providerKeyDraft.trim()
    }
    updater.mutate({ ...runtime, ...secrets })
  }

  function clearSecret(target: 'groq' | CloudProvider) {
    const nextRuntime = target === cloudProvider
      ? { ...runtime, embedding_provider: 'fastembed' as const, embedding_model: PROVIDERS.fastembed.model }
      : runtime
    setRuntime(nextRuntime)
    updater.mutate({ ...nextRuntime, [`clear_${target}_api_key`]: true })
  }

  async function copyApiKey() {
    await navigator.clipboard.writeText(apiKeyDraft)
    setMessage('API key copied')
  }

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-7">
      <section>
        <h2 className="text-base font-semibold text-content-primary">Community admin</h2>
        <p className="mt-1 text-sm text-content-secondary">
          Local runtime, provider credentials, access, and backup.
        </p>
        <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {[
            [ShieldCheck, 'Edition', settings.data?.edition ?? 'community'],
            [KeyRound, 'Identity', settings.data?.identity ?? 'local_single_user'],
            [Cloud, 'Vectors', settings.data?.vector_backend ?? 'pgvector'],
            [HardDrive, 'Storage', settings.data?.blob_backend ?? 'local_fs'],
          ].map(([Icon, label, value]) => {
            const SummaryIcon = Icon as typeof ShieldCheck
            return (
              <div key={String(label)} className="rounded-lg border border-border bg-white p-4">
                <div className="flex items-center gap-2 text-xs font-medium text-content-tertiary">
                  <SummaryIcon className="h-4 w-4" /> {String(label)}
                </div>
                <div className="mt-2 truncate font-mono text-sm text-content-primary">{String(value)}</div>
              </div>
            )
          })}
        </div>
      </section>

      <section className="border-t border-border pt-6">
        <SectionTitle icon={Settings2} title="Runtime" />
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Embedding provider">
            <select
              value={provider}
              onChange={(event) => {
                const next = event.target.value as CommunityRuntimeSettingsUpdate['embedding_provider']
                setProviderKeyDraft('')
                setRuntime({ ...runtime, embedding_provider: next, embedding_model: PROVIDERS[next].model })
              }}
              className="field"
            >
              {Object.entries(PROVIDERS).map(([value, option]) => (
                <option key={value} value={value}>{option.label}</option>
              ))}
            </select>
          </Field>
          <Field label="Embedding model">
            <input value={runtime.embedding_model} onChange={(event) => setRuntime({ ...runtime, embedding_model: event.target.value })} className="field" />
          </Field>
          {cloudProvider && (
            <SecretField
              label={`${PROVIDERS[cloudProvider].label} API key`}
              configured={Boolean(providerConfigured)}
              value={providerKeyDraft}
              onChange={setProviderKeyDraft}
              onClear={() => clearSecret(cloudProvider)}
            />
          )}
          <SecretField
            label="Groq API key"
            configured={Boolean(settings.data?.runtime.groq_configured)}
            value={groqKeyDraft}
            onChange={setGroqKeyDraft}
            onClear={() => clearSecret('groq')}
          />
          <Field label="Groq model">
            <input value={runtime.groq_model} onChange={(event) => setRuntime({ ...runtime, groq_model: event.target.value })} className="field" />
          </Field>
          <Field label="Artifact limit (MB)">
            <input type="number" min={1} max={1024} value={Math.round(runtime.artifact_max_bytes / 1024 / 1024)} onChange={(event) => setRuntime({ ...runtime, artifact_max_bytes: Number(event.target.value) * 1024 * 1024 })} className="field" />
          </Field>
          <Field label="Log level">
            <select value={runtime.log_level} onChange={(event) => setRuntime({ ...runtime, log_level: event.target.value as CommunityRuntimeSettingsUpdate['log_level'] })} className="field">
              {['DEBUG', 'INFO', 'WARNING', 'ERROR'].map((level) => <option key={level}>{level}</option>)}
            </select>
          </Field>
        </div>
        {!providerReady && <div className="mt-3 text-sm text-red-600">An API key is required for cloud embeddings.</div>}
        <button type="button" onClick={saveRuntime} disabled={updater.isPending || !providerReady} className="mt-4 inline-flex items-center gap-2 rounded-md bg-brand-primary px-4 py-2 text-sm font-medium text-white disabled:opacity-50">
          <Save size={16} /> Save runtime settings
        </button>
      </section>

      <section className="border-t border-border pt-6">
        <SectionTitle icon={KeyRound} title="Dashboard access" />
        <div className="flex flex-col gap-2 sm:flex-row">
          <div className="relative min-w-0 flex-1">
            <input value={apiKeyDraft} onChange={(event) => setApiKeyDraft(event.target.value)} type={showApiKey ? 'text' : 'password'} className="field mt-0 pr-10 font-mono" aria-label="Dashboard API key" />
            <button type="button" onClick={() => setShowApiKey(!showApiKey)} className="absolute right-2 top-2 p-1 text-content-tertiary" title={showApiKey ? 'Hide API key' : 'Show API key'}>
              {showApiKey ? <EyeOff size={16} /> : <Eye size={16} />}
            </button>
          </div>
          <button type="button" onClick={copyApiKey} disabled={!apiKeyDraft} className="inline-flex items-center justify-center gap-2 rounded-md border border-border bg-white px-3 py-2 text-sm font-medium text-content-primary disabled:opacity-50"><Copy size={16} /> Copy</button>
          <button type="button" onClick={saveApiKey} className="inline-flex items-center justify-center gap-2 rounded-md bg-brand-primary px-4 py-2 text-sm font-medium text-white"><Save size={16} /> Save</button>
        </div>
      </section>

      <section className="border-t border-border pt-6">
        <SectionTitle icon={HardDrive} title="Backup" />
        <div className="grid gap-3 sm:grid-cols-2">
          <button type="button" onClick={downloadBackup} className="flex items-center justify-center gap-2 rounded-md border border-border bg-white px-4 py-3 text-sm font-medium text-content-primary hover:bg-surface-secondary"><Download className="h-4 w-4" /> Export JSON</button>
          <button type="button" onClick={() => fileRef.current?.click()} className="flex items-center justify-center gap-2 rounded-md border border-border bg-white px-4 py-3 text-sm font-medium text-content-primary hover:bg-surface-secondary"><Upload className="h-4 w-4" /> Import JSON</button>
        </div>
        <input ref={fileRef} type="file" accept="application/json" className="hidden" onChange={(event) => importBackup(event.target.files?.[0])} />
      </section>

      {message && <div className="flex items-center gap-2 text-sm text-content-secondary"><CheckCircle2 className="h-4 w-4 text-status-success" /> {message}</div>}
      {(settings.error || importer.error || updater.error) && <div className="text-sm text-red-600">Community settings request failed</div>}
    </div>
  )
}

function SectionTitle({ icon: Icon, title }: { icon: typeof Settings2; title: string }) {
  return <div className="mb-4 flex items-center gap-2 text-sm font-semibold text-content-primary"><Icon className="h-4 w-4" /> {title}</div>
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <label className="text-xs font-medium text-content-secondary">{label}{children}</label>
}

function SecretField({ label, configured, value, onChange, onClear }: { label: string; configured: boolean; value: string; onChange: (value: string) => void; onClear: () => void }) {
  return (
    <Field label={label}>
      <div className="mt-1 flex items-center gap-2">
        <input value={value} onChange={(event) => onChange(event.target.value)} type="password" placeholder={configured ? 'Configured; enter a replacement' : 'Not configured'} className="field mt-0 min-w-0 flex-1" />
        {configured && <button type="button" onClick={onClear} className="rounded-md border border-border p-2 text-content-secondary hover:bg-surface-secondary" title={`Remove ${label}`}><Trash2 size={16} /></button>}
      </div>
      <span className={`mt-1 block text-xs ${configured ? 'text-status-success' : 'text-content-tertiary'}`}>{configured ? 'Configured' : 'Optional'}</span>
    </Field>
  )
}
