/**
 * Memory Vault — Security Alerts Page
 *
 * Fix KMV-QA-009: The results panel now correctly renders the backend
 * response shapes for PII scans (has_pii / detections / risk_level),
 * injection scans (is_safe / threats), and full scans (pii_scan +
 * injection_scan sub-objects).
 *
 * Previously the page used a generic ScanResult type that did not match
 * the actual API response, causing the results panel to silently fail.
 */
import { useState } from 'react'
import { PageShell } from '@/components/layout/PageShell'
import { StatusBadge } from '@/components/shared/StatusBadge'
import { fullScan, piiScan, injectionScan } from '@/api/security'
import type { PIIScanResult, InjectionScanResult, FullScanResult } from '@/api/types'
import { Shield, Eye, Syringe, AlertTriangle, CheckCircle } from 'lucide-react'

type ScanEntry =
  | { type: 'pii'; result: PIIScanResult }
  | { type: 'injection'; result: InjectionScanResult }
  | { type: 'full'; result: FullScanResult }

// ─── Sub-components ───────────────────────────────────────────────

function PIIResultPanel({ result }: { result: PIIScanResult }) {
  const riskColour: Record<string, string> = {
    none: 'text-status-success',
    low: 'text-status-warning',
    medium: 'text-amber-600',
    high: 'text-status-danger',
  }
  return (
    <div>
      <div className="mb-2 flex items-center gap-2">
        <span className="text-xs font-medium text-content-secondary">PII Risk:</span>
        <span className={`text-xs font-semibold uppercase ${riskColour[result.risk_level] ?? ''}`}>
          {result.risk_level}
        </span>
        {result.has_pii ? (
          <AlertTriangle size={14} className="text-status-danger" />
        ) : (
          <CheckCircle size={14} className="text-status-success" />
        )}
      </div>
      {result.detections.length > 0 ? (
        <div className="space-y-1.5">
          {result.detections.map((d, i) => (
            <div key={i} className="rounded bg-surface-secondary px-3 py-2 text-xs">
              <span className="font-medium text-content-primary">{d.type}</span>
              <span className="ml-2 text-content-secondary">
                &ldquo;{d.value}&rdquo;
              </span>
              <span className="ml-2 text-content-tertiary">
                confidence {Math.round(d.confidence * 100)}%
              </span>
            </div>
          ))}
        </div>
      ) : (
        <p className="text-sm text-status-success">No PII detected</p>
      )}
    </div>
  )
}

function InjectionResultPanel({ result }: { result: InjectionScanResult }) {
  return (
    <div>
      <div className="mb-2 flex items-center gap-2">
        <span className="text-xs font-medium text-content-secondary">Injection Safety:</span>
        {result.is_safe ? (
          <>
            <CheckCircle size={14} className="text-status-success" />
            <span className="text-xs font-semibold text-status-success">Safe</span>
          </>
        ) : (
          <>
            <AlertTriangle size={14} className="text-status-danger" />
            <span className="text-xs font-semibold text-status-danger">Threats Detected</span>
          </>
        )}
      </div>
      {result.threats.length > 0 ? (
        <div className="space-y-1.5">
          {result.threats.map((t, i) => (
            <div key={i} className="rounded bg-surface-secondary px-3 py-2 text-xs">
              <div className="flex items-center gap-2">
                {t.severity && <StatusBadge status={t.severity} />}
                <span className="font-medium text-content-primary">{t.type}</span>
              </div>
              <p className="mt-0.5 text-content-secondary">{t.detail}</p>
            </div>
          ))}
        </div>
      ) : (
        <p className="text-sm text-status-success">No injection threats detected</p>
      )}
      {result.sanitized_content && result.sanitized_content !== result.sanitized_content && (
        <div className="mt-2">
          <p className="text-xs font-medium text-content-secondary">Sanitized content:</p>
          <pre className="mt-1 overflow-auto rounded bg-surface-tertiary p-2 text-xs text-content-primary">
            {result.sanitized_content}
          </pre>
        </div>
      )}
    </div>
  )
}

// ─── Main Page ────────────────────────────────────────────────────

export function SecurityAlertsPage() {
  const [content, setContent] = useState('')
  const [scanning, setScanning] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [results, setResults] = useState<ScanEntry[]>([])

  const runScan = async (type: 'full' | 'pii' | 'injection') => {
    if (!content.trim()) return
    setScanning(true)
    setError(null)
    try {
      if (type === 'full') {
        const result = await fullScan(content)
        setResults((prev) => [{ type: 'full', result }, ...prev])
      } else if (type === 'pii') {
        const result = await piiScan(content)
        setResults((prev) => [{ type: 'pii', result }, ...prev])
      } else {
        const result = await injectionScan(content)
        setResults((prev) => [{ type: 'injection', result }, ...prev])
      }
    } catch (err) {
      console.error('Scan failed:', err)
      setError('Scan failed. Please check the backend connection and try again.')
    } finally {
      setScanning(false)
    }
  }

  return (
    <PageShell>
      {/* Scan input */}
      <div className="rounded-lg border border-border bg-white p-5">
        <h2 className="mb-1 text-sm font-semibold text-content-primary">Inspect Content</h2>
        <p className="mb-3 text-xs text-content-tertiary">
          Paste any text to scan for PII, prompt injection, or other security issues.
        </p>
        <textarea
          value={content}
          onChange={(e) => setContent(e.target.value)}
          placeholder="Paste content to scan for security issues..."
          className="w-full rounded-lg border border-border bg-surface-secondary p-3 text-sm text-content-primary placeholder:text-content-tertiary focus:border-brand-primary focus:outline-none focus:ring-1 focus:ring-brand-primary"
          rows={5}
        />
        {error && (
          <p className="mt-2 text-xs text-status-danger">{error}</p>
        )}
        <div className="mt-3 flex gap-2">
          <button
            onClick={() => runScan('full')}
            disabled={scanning || !content.trim()}
            className="flex items-center gap-1.5 rounded-lg bg-brand-primary px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
          >
            <Shield size={16} />
            {scanning ? 'Scanning…' : 'Full Scan'}
          </button>
          <button
            onClick={() => runScan('pii')}
            disabled={scanning || !content.trim()}
            className="flex items-center gap-1.5 rounded-lg border border-border px-4 py-2 text-sm font-medium text-content-secondary hover:bg-surface-secondary disabled:opacity-50"
          >
            <Eye size={16} /> PII Only
          </button>
          <button
            onClick={() => runScan('injection')}
            disabled={scanning || !content.trim()}
            className="flex items-center gap-1.5 rounded-lg border border-border px-4 py-2 text-sm font-medium text-content-secondary hover:bg-surface-secondary disabled:opacity-50"
          >
            <Syringe size={16} /> Injection Only
          </button>
          {results.length > 0 && (
            <button
              onClick={() => setResults([])}
              className="ml-auto text-xs text-content-tertiary hover:text-content-secondary"
            >
              Clear results
            </button>
          )}
        </div>
      </div>

      {/* Results */}
      {results.length > 0 && (
        <div className="mt-6 space-y-4">
          <h2 className="text-sm font-semibold text-content-primary">
            Scan Results ({results.length})
          </h2>
          {results.map((entry, i) => (
            <div key={i} className="rounded-lg border border-border bg-white p-4">
              <div className="mb-3 flex items-center gap-2">
                <span className="rounded bg-surface-tertiary px-2 py-0.5 text-xs font-semibold uppercase text-content-secondary">
                  {entry.type} scan
                </span>
              </div>

              {entry.type === 'pii' && <PIIResultPanel result={entry.result} />}
              {entry.type === 'injection' && <InjectionResultPanel result={entry.result} />}
              {entry.type === 'full' && (
                <div className="space-y-4">
                  <div>
                    <h4 className="mb-2 text-xs font-semibold uppercase text-content-secondary">
                      PII Analysis
                    </h4>
                    <PIIResultPanel result={entry.result.pii_scan} />
                  </div>
                  <div className="border-t border-border pt-4">
                    <h4 className="mb-2 text-xs font-semibold uppercase text-content-secondary">
                      Injection Analysis
                    </h4>
                    <InjectionResultPanel result={entry.result.injection_scan} />
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Empty state */}
      {results.length === 0 && !scanning && (
        <div className="mt-6 rounded-lg border border-dashed border-border p-8 text-center text-sm text-content-tertiary">
          Enter content above and run a scan to see results here.
        </div>
      )}
    </PageShell>
  )
}
