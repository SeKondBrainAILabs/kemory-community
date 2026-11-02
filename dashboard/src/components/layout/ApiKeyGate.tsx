import { useEffect, useState, type FormEvent, type ReactNode } from 'react'
import { KeyRound } from 'lucide-react'
import { API_UNAUTHORIZED_EVENT, getApiKey, setApiKey } from '@/api/client'
import { getConfig } from '@/lib/runtimeConfig'

/**
 * Asks for the local API key before rendering the dashboard.
 *
 * The key is never served by the dashboard container, so a first visit (or a
 * rejected key) lands here instead of on a page full of 401s.
 */
export function ApiKeyGate({ children }: { children: ReactNode }) {
  const [locked, setLocked] = useState(() => !(getApiKey() || getConfig()?.API_KEY))
  const [draft, setDraft] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [checking, setChecking] = useState(false)

  useEffect(() => {
    const lock = () => setLocked(true)
    window.addEventListener(API_UNAUTHORIZED_EVENT, lock)
    return () => window.removeEventListener(API_UNAUTHORIZED_EVENT, lock)
  }, [])

  async function unlock(event: FormEvent) {
    event.preventDefault()
    const key = draft.trim()
    if (!key) return
    setChecking(true)
    setError(null)
    try {
      const base = (getConfig()?.API_URL ?? '').replace(/\/$/, '')
      const response = await fetch(`${base}/api/v1/namespaces`, { headers: { 'X-API-Key': key } })
      if (response.status === 401) {
        setError('That key was rejected. It must match KEMORY_LOCAL_API_KEY on the API container.')
        return
      }
      if (!response.ok) {
        setError(`The API answered ${response.status}. Check that it is running.`)
        return
      }
      setApiKey(key)
      setDraft('')
      setLocked(false)
    } catch {
      setError('Could not reach the API. Check that it is running.')
    } finally {
      setChecking(false)
    }
  }

  if (!locked) return <>{children}</>

  return (
    <div className="flex min-h-screen items-center justify-center bg-surface-secondary px-4">
      <form onSubmit={unlock} className="w-full max-w-md rounded-lg border border-border bg-white p-6 shadow-sm">
        <div className="mb-4 flex items-center gap-2 text-content-primary">
          <KeyRound size={20} />
          <h1 className="text-lg font-semibold">Enter your Kemory API key</h1>
        </div>
        <p className="mb-4 text-sm text-content-secondary">
          Use the value of <code className="font-mono">KEMORY_LOCAL_API_KEY</code> from the <code className="font-mono">.env</code> file
          you started the stack with. It is stored in this browser only.
        </p>
        <input
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          type="password"
          autoFocus
          className="field mt-0 font-mono"
          aria-label="API key"
        />
        {error && <div className="mt-3 text-sm text-red-600">{error}</div>}
        <button
          type="submit"
          disabled={checking || !draft.trim()}
          className="mt-4 inline-flex w-full items-center justify-center rounded-md bg-brand-primary px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
        >
          {checking ? 'Checking…' : 'Unlock dashboard'}
        </button>
      </form>
    </div>
  )
}
