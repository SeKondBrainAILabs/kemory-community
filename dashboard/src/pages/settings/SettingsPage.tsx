import { useRef, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { Download, KeyRound, Upload } from 'lucide-react'
import { exportCommunityBundle, getCommunitySettings, importCommunityBundle } from '@/api/community'
import { getApiKey, setApiKey } from '@/api/client'

export function SettingsPage() {
  const fileRef = useRef<HTMLInputElement | null>(null)
  const [apiKeyDraft, setApiKeyDraft] = useState(getApiKey() ?? '')
  const [message, setMessage] = useState<string | null>(null)
  const settings = useQuery({ queryKey: ['community-settings'], queryFn: getCommunitySettings })
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
    const parsed = JSON.parse(await file.text())
    importer.mutate(parsed)
  }

  function saveApiKey() {
    setApiKey(apiKeyDraft.trim())
    setMessage('API key saved')
  }

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6 px-6 py-6">
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

      <section className="rounded-lg border border-border bg-white p-5">
        <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-content-primary">
          <KeyRound className="h-4 w-4" />
          API Key
        </div>
        <div className="flex flex-col gap-3 sm:flex-row">
          <input
            value={apiKeyDraft}
            onChange={(event) => setApiKeyDraft(event.target.value)}
            type="password"
            className="min-w-0 flex-1 rounded-md border border-border px-3 py-2 text-sm outline-none focus:border-brand-primary"
            placeholder="kemory community API key"
          />
          <button
            type="button"
            onClick={saveApiKey}
            className="rounded-md bg-brand-primary px-4 py-2 text-sm font-medium text-white"
          >
            Save
          </button>
        </div>
      </section>

      <section className="rounded-lg border border-border bg-white p-5">
        <div className="mb-4 grid gap-3 sm:grid-cols-2">
          <button
            type="button"
            onClick={downloadBackup}
            className="flex items-center justify-center gap-2 rounded-md border border-border px-4 py-3 text-sm font-medium text-content-primary hover:bg-surface-secondary"
          >
            <Download className="h-4 w-4" />
            Export JSON
          </button>
          <button
            type="button"
            onClick={() => fileRef.current?.click()}
            className="flex items-center justify-center gap-2 rounded-md border border-border px-4 py-3 text-sm font-medium text-content-primary hover:bg-surface-secondary"
          >
            <Upload className="h-4 w-4" />
            Import JSON
          </button>
        </div>
        <input
          ref={fileRef}
          type="file"
          accept="application/json"
          className="hidden"
          onChange={(event) => importBackup(event.target.files?.[0])}
        />
        {message && <div className="text-sm text-content-secondary">{message}</div>}
        {importer.error && <div className="text-sm text-red-600">Import failed</div>}
      </section>
    </div>
  )
}
