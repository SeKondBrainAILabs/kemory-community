import { useState } from 'react'
import * as Dialog from '@radix-ui/react-dialog'
import { X } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { ConnectorId } from './ConnectorsPage'
import { ClaudeCodeWizard } from './wizards/ClaudeCodeWizard'
import { ClaudeDesktopWizard } from './wizards/ClaudeDesktopWizard'
import { AgentWizard } from './wizards/AgentWizard'
import { CognitionBridgeWizard } from './wizards/CognitionBridgeWizard'
import { WebhookWizard } from './wizards/WebhookWizard'
import { McpClientWizard } from './wizards/McpClientWizard'
import { mcpClientDescriptors } from './wizards/mcpClientDescriptors'

interface Props {
  connectorId: ConnectorId
  onClose: () => void
}

const titles: Record<ConnectorId, string> = {
  'claude-code': 'Set up Claude Code',
  'claude-desktop': 'Set up Claude Desktop',
  cursor: 'Set up Cursor',
  windsurf: 'Set up Windsurf',
  cline: 'Set up Cline',
  codex: 'Set up ChatGPT / Codex CLI',
  'gemini-cli': 'Set up Gemini CLI',
  ollama: 'Set up Ollama',
  'custom-mcp': 'Set up Custom MCP Client',
  'custom-agent': 'Register Custom Agent',
  'cognition-os': 'Configure Cognition OS Bridge',
  webhook: 'Configure Webhook',
}

const GENERIC_MCP_IDS: ReadonlySet<ConnectorId> = new Set<ConnectorId>([
  'cursor',
  'windsurf',
  'cline',
  'codex',
  'gemini-cli',
  'ollama',
  'custom-mcp',
])

export function ConnectorWizard({ connectorId, onClose }: Props) {
  return (
    <Dialog.Root open onOpenChange={(open) => !open && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/40 data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0" />
        <Dialog.Content className="fixed left-1/2 top-1/2 z-50 flex max-h-[90vh] w-[95vw] max-w-4xl -translate-x-1/2 -translate-y-1/2 flex-col rounded-xl border border-border bg-white shadow-lg">
          <div className="flex items-center justify-between border-b border-border px-6 py-4">
            <Dialog.Title className="text-base font-semibold text-content-primary">
              {titles[connectorId]}
            </Dialog.Title>
            <Dialog.Close asChild>
              <button className="rounded-md p-1 text-content-tertiary hover:bg-surface-secondary hover:text-content-primary transition-colors">
                <X size={18} />
              </button>
            </Dialog.Close>
          </div>
          <div className="overflow-y-auto px-6 py-5">
            {connectorId === 'claude-code' && <ClaudeCodeWizard onClose={onClose} />}
            {connectorId === 'claude-desktop' && <ClaudeDesktopWizard onClose={onClose} />}
            {connectorId === 'custom-agent' && <AgentWizard onClose={onClose} />}
            {connectorId === 'cognition-os' && <CognitionBridgeWizard onClose={onClose} />}
            {connectorId === 'webhook' && <WebhookWizard onClose={onClose} />}
            {GENERIC_MCP_IDS.has(connectorId) && mcpClientDescriptors[connectorId] && (
              <McpClientWizard
                descriptor={mcpClientDescriptors[connectorId]}
                onClose={onClose}
              />
            )}
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}

// Shared wizard step components
export function WizardSteps({ current, total }: { current: number; total: number }) {
  return (
    <div className="mb-5 flex items-center gap-2">
      {Array.from({ length: total }, (_, i) => (
        <div
          key={i}
          className={cn(
            'h-1.5 flex-1 rounded-full transition-colors',
            i < current ? 'bg-brand-primary' : i === current ? 'bg-brand-primary/50' : 'bg-surface-secondary',
          )}
        />
      ))}
      <span className="ml-2 text-xs text-content-tertiary">
        Step {current + 1} of {total}
      </span>
    </div>
  )
}

export function WizardNav({
  step,
  total,
  onBack,
  onNext,
  nextLabel,
  nextDisabled,
}: {
  step: number
  total: number
  onBack: () => void
  onNext: () => void
  nextLabel?: string
  nextDisabled?: boolean
}) {
  return (
    <div className="mt-6 flex justify-between">
      <button
        onClick={onBack}
        disabled={step === 0}
        className={cn(
          'rounded-lg border border-border px-4 py-2 text-sm font-medium transition-colors',
          step === 0
            ? 'cursor-not-allowed opacity-40'
            : 'text-content-secondary hover:bg-surface-secondary',
        )}
      >
        Back
      </button>
      <button
        onClick={onNext}
        disabled={nextDisabled}
        className={cn(
          'rounded-lg px-5 py-2 text-sm font-medium text-white transition-colors',
          nextDisabled
            ? 'cursor-not-allowed bg-brand-primary/40'
            : 'bg-brand-primary hover:bg-brand-primary/90',
        )}
      >
        {nextLabel ?? (step === total - 1 ? 'Done' : 'Next')}
      </button>
    </div>
  )
}

export function CodeBlock({ code, label }: { code: string; label?: string }) {
  const [copied, setCopied] = useState(false)

  function copy() {
    navigator.clipboard.writeText(code)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div className="relative mt-3">
      {label && <p className="mb-1 text-xs font-medium text-content-secondary">{label}</p>}
      <pre className="max-h-56 overflow-auto rounded-lg bg-gray-900 p-4 text-xs text-gray-100 leading-relaxed">
        {code}
      </pre>
      <button
        onClick={copy}
        className="absolute right-2 top-2 rounded-md bg-gray-700 px-2.5 py-1 text-xs text-gray-200 hover:bg-gray-600 transition-colors"
      >
        {copied ? 'Copied!' : 'Copy'}
      </button>
    </div>
  )
}
