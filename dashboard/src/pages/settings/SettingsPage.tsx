import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Download, KeyRound, Save, Settings2, Upload } from 'lucide-react'
import {
  exportCommunityBundle,
  getCommunitySettings,
  importCommunityBundle,
  updateCommunitySettings,
  type CommunityRuntimeSettingsUpdate,
} from '@/api/community'
import { getApiKey, setApiKey } from '@/api/client'

const DEFAULT_RUNTIME: CommunityRuntimeSettingsUpdate = {
  embedding_provider: 'fastembed',
  embedding_model: 'BAAI/bge-small-en-v1.5',
  groq_model: 'llama-3.3-70b-versatile',
  artifact_max_bytes: 50 * 1024 * 1024,
  log_level: 'INFO',
}

export function SettingsPage() {
  const queryClient = useQueryClient()
  const fileRef = useRef<HTMLInputElement | null>(null)
  const [apiKeyDraft, setApiKeyDraft] = useState(getApiKey() ?? '')
  const [groqKeyDraft, setGroqKeyDraft] = useState('')
  const [runtime, setRuntime] = useState<CommunityRuntimeSettingsUpdate>(DEFAULT_RUNTIME)
  const [message, setMessage] = useState<string | null>(null)
  const settings = useQuery({ queryKey: ['community-settings'], queryFn: getCommunitySettings })

  useEffect(() => {
    if (!settings.data?.runtime) return
    const { groq_configured: _configured, ...values } = settings.data.runtime
    setRuntime(values)
  }, [settings.data])

  const updater = useMutation({
    mutationFn: updateCommunitySettings,
    onSuccess: () => {
      setGroqKeyDraft('')
      setMessage('Runtime settings saved')
      queryClient.invalidateQueries({ queryKey: ['community-settings'] })
    },
  })
  const importer = useMutation({
    mutationFn: importCommunityBundle,
    onSuccess: (result) => setMessage(`Imported ${result.imported} memories`),
  })

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
    setMessage('API key saved')
  }

  function saveRuntime() {
    updater.mutate({
      ...runtime,
      groq_api_key: groqKeyDraft.trim() || undefined,
    })
  }

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6">
      <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {[
          ['Edition', settings.data?.edition ?? 'community'],
          ['Identity', settings.data?.identity ?? 'local_single_user'],
          ['Vectors', settings.data?.vector_backend ?? 'pgvector'],
          ['Storage', settings.data?.blob_backend ?? 'local_fs'],
        ].map(([label, value]) => (
          <div key={label} className="rounded-lg border border-border bg-white p-4">
            <div className="text-xs font-medium uppercase text-content-tertiary">{label}</div>
            <div className="mt-2 truncate font-mono text-sm text-content-primary">{value}</div>
          </div>
        ))}
      </section>

      <section className="border-b border-border pb-6">
        <div className="mb-4 flex items-center gap-2 text-sm font-semibold text-content-primary">
          <Settings2 className="h-4 w-4" /> Runtime
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label={`Groq API key${settings.data?.runtime.groq_configured ? ' (configured)' : ''}`}>
            <input value={groqKeyDraft} onChange={(event) => setGroqKeyDraft(event.target.value)} type="password" placeholder="Enter a new key to replace it" className="field" />
          </Field>
          <Field label="Groq model">
            <input value={runtime.groq_model} onChange={(event) => setRuntime({ ...runtime, groq_model: event.target.value })} className="field" />
          </Field>
          <Field label="Embedding provider">
            <select value={runtime.embedding_provider} onChange={(event) => {
              const provider = event.target.value as CommunityRuntimeSettingsUpdate['embedding_provider']
              const models = { fastembed: 'BAAI/bge-small-en-v1.5', openai: 'text-embedding-3-small', voyage: 'voyage-3.5', cohere: 'embed-v4.0' }
              setRuntime({ ...runtime, embedding_provider: provider, embedding_model: models[provider] })
            }} className="field">
              <option value="fastembed">FastEmbed</option>
              <option value="openai">OpenAI</option>
              <option value="voyage">Voyage</option>
              <option value="cohere">Cohere</option>
            </select>
          </Field>
          <Field label="Embedding model">
            <input value={runtime.embedding_model} onChange={(event) => setRuntime({ ...runtime, embedding_model: event.target.value })} className="field" />
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
        <button type="button" onClick={saveRuntime} disabled={updater.isPending} className="mt-4 inline-flex items-center gap-2 rounded-md bg-brand-primary px-4 py-2 text-sm font-medium text-white disabled:opacity-50">
          <Save size={16} /> Save runtime settings
        </button>
      </section>

      <section className="border-b border-border pb-6">
        <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-content-primary"><KeyRound className="h-4 w-4" /> Dashboard API key</div>
        <div className="flex flex-col gap-3 sm:flex-row">
          <input value={apiKeyDraft} onChange={(event) => setApiKeyDraft(event.target.value)} type="password" className="field min-w-0 flex-1" placeholder="kemory community API key" />
          <button type="button" onClick={saveApiKey} className="rounded-md bg-brand-primary px-4 py-2 text-sm font-medium text-white">Save</button>
        </div>
      </section>

      <section>
        <div className="grid gap-3 sm:grid-cols-2">
          <button type="button" onClick={downloadBackup} className="flex items-center justify-center gap-2 rounded-md border border-border bg-white px-4 py-3 text-sm font-medium text-content-primary hover:bg-surface-secondary"><Download className="h-4 w-4" /> Export JSON</button>
          <button type="button" onClick={() => fileRef.current?.click()} className="flex items-center justify-center gap-2 rounded-md border border-border bg-white px-4 py-3 text-sm font-medium text-content-primary hover:bg-surface-secondary"><Upload className="h-4 w-4" /> Import JSON</button>
        </div>
        <input ref={fileRef} type="file" accept="application/json" className="hidden" onChange={(event) => importBackup(event.target.files?.[0])} />
        {message && <div className="mt-3 text-sm text-content-secondary">{message}</div>}
        {(importer.error || updater.error) && <div className="mt-3 text-sm text-red-600">Save failed</div>}
      </section>
    </div>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <label className="text-xs font-medium text-content-secondary">{label}{children}</label>
}
