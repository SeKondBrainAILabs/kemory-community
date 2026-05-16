import { useEffect, useMemo, useRef, useState } from 'react'
import { Check, Copy, Loader2, RefreshCw, Zap } from 'lucide-react'
import { startPair, getPairStatus } from '@/api/pair'
import type { PairStartResponse, PairStatusResponse } from '@/api/pair'

const POLL_INTERVAL_MS = 2500

function CopyButton({ value, label = 'Copy' }: { value: string; label?: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <button
      type="button"
      onClick={async () => {
        await navigator.clipboard.writeText(value)
        setCopied(true)
        setTimeout(() => setCopied(false), 1500)
      }}
      className="inline-flex items-center gap-1 rounded-md border border-border bg-white px-2 py-1 text-xs text-content-secondary hover:bg-surface-secondary"
    >
      {copied ? <Check size={12} className="text-status-success" /> : <Copy size={12} />}
      {copied ? 'Copied' : label}
    </button>
  )
}

function buildPrompt(claimUrl: string, clientHint?: string): string {
  const clientLabel = clientHint
    ? `\`${clientHint}\``
    : `your name, e.g. ChatGPT, Cursor, Claude Desktop`
  return `I want to connect to Kemory — my persistent, cross-session, cross-AI memory store.

Please POST to this URL with your client name to claim a connection and receive your API key, brief, and the list of memory tools:

  ${claimUrl}

Request body (JSON):
  { "client_name": "<${clientLabel}>" }

The response contains:
  - api_key — use it as the X-API-Key header for every subsequent call to ${'`mcp_url`'}.
  - mcp_url — the base for your MCP transport (POST /tools/list, /tools/call, /prompts/get).
  - brief — your instructions for using Kemory. Read it carefully. Refresh it on every reconnect via prompts/get name="kemory_brief".
  - tools — the list of memory tools available right now.

After claiming:
  1. Store a small test memory and immediately recall it ("Connected to Kemory at <timestamp> from <your name>").
  2. Report back to me: "✅ Connected to Kemory as <agent_name> — round-trip test passed."
  3. From now on, use Kemory as your default memory store. Confirm with me before storing anything personal.`
}

interface QuickConnectContentProps {
  /** Pre-fills the prompt's client_name placeholder. */
  clientHint?: string
  /** Hide the outer card chrome (used inside a wizard dialog). */
  embedded?: boolean
}

/**
 * The shared pair‑claim UX: generate link → show prompt → poll for claim.
 * Used both as the standalone Connectors panel and inside per‑client modals.
 */
export function QuickConnectContent({ clientHint, embedded = false }: QuickConnectContentProps) {
  const [pair, setPair] = useState<PairStartResponse | null>(null)
  const [status, setStatus] = useState<PairStatusResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string>('')
  const pollTimer = useRef<number | null>(null)

  async function generate() {
    setLoading(true)
    setError('')
    setStatus(null)
    try {
      const resp = await startPair(clientHint ?? 'dashboard quick-connect')
      setPair(resp)
    } catch (err: any) {
      const body = await err?.response?.json?.().catch(() => null)
      setError(body?.detail ?? err?.message ?? 'Failed to start pairing')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (!pair?.code) return
    let cancelled = false
    async function poll() {
      try {
        const s = await getPairStatus(pair!.code)
        if (cancelled) return
        setStatus(s)
        if (s.claimed) return
        if (s.expires_in <= 0) return
        pollTimer.current = window.setTimeout(poll, POLL_INTERVAL_MS)
      } catch {
        // Status 404 = expired or revoked; stop polling.
      }
    }
    poll()
    return () => {
      cancelled = true
      if (pollTimer.current) window.clearTimeout(pollTimer.current)
    }
  }, [pair?.code])

  const prompt = useMemo(() => (pair ? buildPrompt(pair.claim_url, clientHint) : ''), [pair, clientHint])
  const expired = !!(status && !status.claimed && status.expires_in <= 0)

  const minutesLeft = Math.max(0, Math.round((status?.expires_in ?? pair?.expires_in ?? 0) / 60))

  return (
    <>
      {!embedded && (
        <div className="flex items-start justify-between gap-4">
          <div className="flex items-start gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-brand-primary/10 text-brand-primary">
              <Zap size={20} />
            </div>
            <div>
              <h2 className="text-sm font-semibold text-content-primary">Quick connect any AI</h2>
              <p className="mt-1 text-xs text-content-secondary">
                Generate a 5‑minute connection link, paste one prompt into ChatGPT, Claude, Cursor, or any
                other AI — it self‑registers, reads its brief, runs a round‑trip test, and starts using
                Kemory as its default memory.
              </p>
            </div>
          </div>
          {pair && (
            <button
              type="button"
              onClick={generate}
              disabled={loading}
              className="inline-flex items-center gap-1 rounded-md border border-border bg-white px-2.5 py-1 text-xs text-content-secondary hover:bg-surface-secondary"
            >
              <RefreshCw size={12} /> New link
            </button>
          )}
        </div>
      )}

      {embedded && (
        <p className="text-xs text-content-secondary">
          {clientHint
            ? `Generate a 5‑minute connection link and paste the prompt below into ${clientHint}. It will self‑register, read its brief, and run a round‑trip test — no config file, no API key copy/paste.`
            : 'Generate a 5‑minute connection link and paste the prompt into your AI.'}
        </p>
      )}

      {!pair && (
        <button
          type="button"
          onClick={generate}
          disabled={loading}
          className="mt-4 inline-flex items-center gap-2 rounded-lg bg-brand-primary px-4 py-2 text-sm font-medium text-white hover:bg-brand-primary/90 disabled:opacity-60"
        >
          {loading ? <Loader2 size={14} className="animate-spin" /> : <Zap size={14} />}
          Generate connection link
        </button>
      )}

      {error && (
        <div className="mt-3 rounded-lg bg-status-danger/10 px-3 py-2 text-xs text-status-danger">{error}</div>
      )}

      {pair && (
        <div className="mt-4 space-y-3">
          <div>
            <div className="mb-1 flex items-center justify-between">
              <label className="text-xs font-medium text-content-secondary">
                Connection link <span className="text-content-tertiary">(expires in {minutesLeft} min)</span>
              </label>
              <div className="flex items-center gap-2">
                {embedded && (
                  <button
                    type="button"
                    onClick={generate}
                    disabled={loading}
                    className="inline-flex items-center gap-1 rounded-md border border-border bg-white px-2 py-1 text-xs text-content-secondary hover:bg-surface-secondary"
                  >
                    <RefreshCw size={12} /> New link
                  </button>
                )}
                <CopyButton value={pair.claim_url} label="Copy URL" />
              </div>
            </div>
            <div className="rounded-lg border border-border bg-white px-3 py-2">
              <code className="break-all font-mono text-xs text-content-primary">{pair.claim_url}</code>
            </div>
          </div>

          <div>
            <div className="mb-1 flex items-center justify-between">
              <label className="text-xs font-medium text-content-secondary">
                Prompt — paste this entire block into your AI
              </label>
              <CopyButton value={prompt} label="Copy prompt" />
            </div>
            <pre className="max-h-72 overflow-auto rounded-lg bg-gray-900 p-3 text-[11px] leading-relaxed text-gray-100">
              {prompt}
            </pre>
          </div>

          {status?.claimed ? (
            <div className="flex items-center gap-2 rounded-lg bg-status-success/10 px-3 py-2 text-xs text-status-success">
              <Check size={14} />
              Connected as <span className="font-medium">{status.agent_name}</span>
              {status.client_name && <span className="text-content-secondary">— {status.client_name}</span>}
            </div>
          ) : expired ? (
            <div className="rounded-lg bg-status-warning/10 px-3 py-2 text-xs text-status-warning">
              Link expired before being claimed. Click <span className="font-medium">New link</span> to try again.
            </div>
          ) : (
            <div className="flex items-center gap-2 rounded-lg bg-surface-secondary px-3 py-2 text-xs text-content-secondary">
              <Loader2 size={12} className="animate-spin" />
              Waiting for an AI to claim this link…
            </div>
          )}
        </div>
      )}
    </>
  )
}

export function QuickConnectPanel() {
  return (
    <div className="mb-8 rounded-xl border border-brand-primary/20 bg-gradient-to-br from-brand-primary/5 to-white p-5 shadow-sm">
      <QuickConnectContent />
    </div>
  )
}
