/**
 * Kemory dashboard — Devices page (chats-v1 UI).
 *
 * Lists and manages Chrome Extension API keys (one per install).
 * Backed by /api/v1/extension/keys (v3.31.0).
 *
 * The plaintext API key is returned ONCE on mint. The reveal modal
 * holds it in component state for as long as it's open; we never
 * cache it in React Query or localStorage.
 */
import { useMemo, useState } from 'react'
import * as Dialog from '@radix-ui/react-dialog'
import { Copy, Plus, Smartphone, Trash2, X } from 'lucide-react'
import type { ColumnDef } from '@tanstack/react-table'
import { PageShell } from '@/components/layout/PageShell'
import { DataTable } from '@/components/shared/DataTable'
import { StatusBadge } from '@/components/shared/StatusBadge'
import { ConfirmDialog } from '@/components/shared/ConfirmDialog'
import {
  useExtensionKeys,
  useMintExtensionKey,
  useRevokeExtensionKey,
} from '@/hooks/useExtensionKeys'
import type { ExtensionKeyInfo } from '@/api/extensionKeys'

const DEFAULT_SCOPES = ['memory:read', 'memory:write', 'chat:write']

export function DevicesPage() {
  const { data: keys, isLoading, isError, error } = useExtensionKeys()
  const mintMutation = useMintExtensionKey()
  const revokeMutation = useRevokeExtensionKey()

  const [mintDialogOpen, setMintDialogOpen] = useState(false)
  const [label, setLabel] = useState('')
  const [mintError, setMintError] = useState<string | null>(null)
  const [revealKey, setRevealKey] = useState<string | null>(null)
  const [revealMeta, setRevealMeta] = useState<{ label: string; scopes: string[] } | null>(null)
  const [confirmRevoke, setConfirmRevoke] = useState<ExtensionKeyInfo | null>(null)
  const [copied, setCopied] = useState(false)

  function handleMintSubmit(e: React.FormEvent) {
    e.preventDefault()
    setMintError(null)
    const trimmed = label.trim()
    if (!trimmed) {
      setMintError('Label is required (e.g. "MacBook Chrome")')
      return
    }
    mintMutation.mutate(
      {
        label: trimmed,
        // Browser-side: crypto.randomUUID for the installation_id so
        // re-minting from the same device rotates instead of stacking.
        installation_id: crypto.randomUUID(),
        scopes: DEFAULT_SCOPES,
      },
      {
        onSuccess: (res) => {
          setMintDialogOpen(false)
          setLabel('')
          setRevealKey(res.api_key)
          setRevealMeta({ label: res.label, scopes: res.scopes })
        },
        onError: (err) => {
          setMintError((err as Error).message ?? 'Failed to mint key')
        },
      },
    )
  }

  function handleRevoke() {
    if (!confirmRevoke) return
    revokeMutation.mutate(confirmRevoke.key_id, {
      onSuccess: () => setConfirmRevoke(null),
    })
  }

  async function handleCopy() {
    if (!revealKey) return
    try {
      await navigator.clipboard.writeText(revealKey)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      // Fallback: select + manual copy. (Some sandboxed origins block
      // clipboard.writeText; we just leave the value visible for the user.)
    }
  }

  function handleRevealClose() {
    setRevealKey(null)
    setRevealMeta(null)
    setCopied(false)
  }

  const columns = useMemo<ColumnDef<ExtensionKeyInfo>[]>(
    () => [
      {
        accessorKey: 'label',
        header: 'Label',
        cell: ({ row }) => (
          <div className="flex items-center gap-2">
            <Smartphone size={14} className="text-content-tertiary" />
            <span className="font-medium text-content-primary">
              {row.original.label || (
                <span className="italic text-content-tertiary">unnamed</span>
              )}
            </span>
          </div>
        ),
      },
      {
        accessorKey: 'installation_id',
        header: 'Installation',
        cell: ({ row }) => (
          <span className="font-mono text-[11px] text-content-tertiary">
            {row.original.installation_id
              ? row.original.installation_id.slice(0, 8) + '…'
              : '—'}
          </span>
        ),
      },
      {
        accessorKey: 'scopes',
        header: 'Scopes',
        cell: ({ row }) => (
          <div className="flex flex-wrap gap-1">
            {row.original.scopes.map((s) => (
              <span
                key={s}
                className="rounded-full bg-surface-secondary px-2 py-0.5 font-mono text-[10px] text-content-secondary"
              >
                {s}
              </span>
            ))}
          </div>
        ),
      },
      {
        accessorKey: 'status',
        header: 'Status',
        cell: ({ row }) => <StatusBadge status={row.original.status} />,
      },
      {
        accessorKey: 'last_used_at',
        header: 'Last used',
        cell: ({ row }) => (
          <span className="text-xs text-content-tertiary">
            {row.original.last_used_at ?? 'never'}
          </span>
        ),
      },
      {
        id: 'actions',
        header: '',
        cell: ({ row }) =>
          row.original.status !== 'revoked' ? (
            <div className="flex justify-end">
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation()
                  setConfirmRevoke(row.original)
                }}
                className="rounded p-1 text-content-tertiary hover:bg-red-50 hover:text-status-danger"
                title="Revoke key"
              >
                <Trash2 size={14} />
              </button>
            </div>
          ) : null,
      },
    ],
    [],
  )

  return (
    <PageShell>
      <div className="mb-4 flex items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-content-primary">Devices</h1>
          <p className="mt-1 text-sm text-content-secondary">
            Per-install API keys for the Kanvas Chrome Extension. Mint a key,
            paste it into the extension on that device, and it can push chats
            to Kemory.
          </p>
        </div>
        <button
          type="button"
          onClick={() => {
            setLabel('')
            setMintError(null)
            setMintDialogOpen(true)
          }}
          className="inline-flex items-center gap-1.5 rounded-lg bg-brand-primary px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-700"
        >
          <Plus size={14} />
          Mint a key
        </button>
      </div>

      {isLoading ? (
        <div className="rounded-lg border border-border bg-white p-8 text-center text-sm text-content-tertiary">
          Loading keys…
        </div>
      ) : isError ? (
        <div className="rounded-lg border border-status-danger bg-red-50 p-8 text-center text-sm text-status-danger">
          Failed to load extension keys. {(error as Error)?.message}
        </div>
      ) : (
        <DataTable columns={columns} data={keys ?? []} />
      )}

      {/* Mint dialog */}
      <Dialog.Root open={mintDialogOpen} onOpenChange={setMintDialogOpen}>
        <Dialog.Portal>
          <Dialog.Overlay className="fixed inset-0 z-50 bg-black/40" />
          <Dialog.Content className="fixed left-1/2 top-1/2 z-50 w-full max-w-md -translate-x-1/2 -translate-y-1/2 rounded-xl border border-border bg-white p-6 shadow-lg">
            <Dialog.Title className="text-base font-semibold text-content-primary">
              Mint extension key
            </Dialog.Title>
            <Dialog.Description className="mt-1 text-sm text-content-secondary">
              The plaintext key is shown ONCE on the next screen — copy it
              into the extension before closing.
            </Dialog.Description>
            <form onSubmit={handleMintSubmit} className="mt-4 space-y-3 text-sm">
              <div>
                <label className="mb-1 block text-xs font-medium text-content-secondary">
                  Device label
                </label>
                <input
                  type="text"
                  value={label}
                  onChange={(e) => setLabel(e.target.value)}
                  placeholder="MacBook Chrome"
                  className="w-full rounded-lg border border-border bg-white px-3 py-2 text-sm focus:border-brand-primary focus:outline-none"
                  autoFocus
                />
              </div>
              <div className="rounded border border-border bg-surface-secondary/50 p-2 text-xs text-content-secondary">
                Scopes:{' '}
                {DEFAULT_SCOPES.map((s) => (
                  <span
                    key={s}
                    className="mr-1 rounded-full bg-white px-1.5 py-0.5 font-mono text-[10px]"
                  >
                    {s}
                  </span>
                ))}
              </div>
              {mintError && (
                <div className="rounded border border-status-danger bg-red-50 p-2 text-xs text-status-danger">
                  {mintError}
                </div>
              )}
              <div className="mt-4 flex justify-end gap-2">
                <button
                  type="button"
                  onClick={() => setMintDialogOpen(false)}
                  className="rounded-lg border border-border px-4 py-2 text-sm font-medium text-content-secondary hover:bg-surface-secondary"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={mintMutation.isPending}
                  className="rounded-lg bg-brand-primary px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
                >
                  {mintMutation.isPending ? 'Minting…' : 'Mint key'}
                </button>
              </div>
            </form>
            <Dialog.Close asChild>
              <button className="absolute right-4 top-4 text-content-tertiary hover:text-content-primary">
                <X size={16} />
              </button>
            </Dialog.Close>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>

      {/* Reveal dialog — shows plaintext key once */}
      <Dialog.Root open={!!revealKey} onOpenChange={(open) => !open && handleRevealClose()}>
        <Dialog.Portal>
          <Dialog.Overlay className="fixed inset-0 z-50 bg-black/40" />
          <Dialog.Content className="fixed left-1/2 top-1/2 z-50 w-full max-w-md -translate-x-1/2 -translate-y-1/2 rounded-xl border border-border bg-white p-6 shadow-lg">
            <Dialog.Title className="text-base font-semibold text-content-primary">
              Save this key now
            </Dialog.Title>
            <Dialog.Description className="mt-1 text-sm text-content-secondary">
              Paste it into the Kanvas Chrome Extension on{' '}
              <span className="font-medium">{revealMeta?.label}</span>. It will
              not be shown again — if you lose it, mint a new one.
            </Dialog.Description>
            <div className="mt-4 space-y-3">
              <textarea
                value={revealKey ?? ''}
                readOnly
                rows={3}
                onFocus={(e) => e.target.select()}
                className="w-full rounded-lg border border-border bg-surface-secondary p-3 font-mono text-[11px] text-content-primary"
              />
              <button
                type="button"
                onClick={handleCopy}
                className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-white px-3 py-1.5 text-sm font-medium text-content-secondary hover:bg-surface-secondary"
              >
                <Copy size={14} />
                {copied ? 'Copied!' : 'Copy to clipboard'}
              </button>
              <div className="rounded border border-amber-200 bg-amber-50 p-2 text-xs text-amber-700">
                <strong>One-time reveal.</strong> The plaintext value is never
                stored. After this dialog closes, only the device label and
                installation id are visible in the list.
              </div>
              <div className="flex justify-end">
                <button
                  type="button"
                  onClick={handleRevealClose}
                  className="rounded-lg bg-brand-primary px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700"
                >
                  I've saved it
                </button>
              </div>
            </div>
            <Dialog.Close asChild>
              <button className="absolute right-4 top-4 text-content-tertiary hover:text-content-primary">
                <X size={16} />
              </button>
            </Dialog.Close>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>

      <ConfirmDialog
        open={!!confirmRevoke}
        onOpenChange={(open) => !open && setConfirmRevoke(null)}
        title="Revoke this key?"
        description={
          confirmRevoke
            ? `The extension on "${confirmRevoke.label}" will get 401 on its next request and stop being able to push chats. This can't be undone — you'd have to mint a fresh key.`
            : ''
        }
        confirmLabel="Revoke"
        variant="danger"
        onConfirm={handleRevoke}
      />
    </PageShell>
  )
}
