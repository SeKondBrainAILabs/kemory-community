import * as Dialog from '@radix-ui/react-dialog'
import { X } from 'lucide-react'

interface ConfirmDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  description: string
  confirmLabel?: string
  variant?: 'danger' | 'default'
  onConfirm: () => void
}

export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  confirmLabel = 'Confirm',
  variant = 'default',
  onConfirm,
}: ConfirmDialogProps) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/40" />
        <Dialog.Content className="fixed left-1/2 top-1/2 z-50 w-full max-w-md -translate-x-1/2 -translate-y-1/2 rounded-xl border border-border bg-white p-6 shadow-lg">
          <Dialog.Title className="text-base font-semibold text-content-primary">
            {title}
          </Dialog.Title>
          <Dialog.Description className="mt-2 text-sm text-content-secondary">
            {description}
          </Dialog.Description>
          <div className="mt-6 flex justify-end gap-3">
            <button
              onClick={() => onOpenChange(false)}
              className="rounded-lg border border-border px-4 py-2 text-sm font-medium text-content-secondary hover:bg-surface-secondary"
            >
              Cancel
            </button>
            <button
              onClick={() => {
                onConfirm()
                onOpenChange(false)
              }}
              className={
                variant === 'danger'
                  ? 'rounded-lg bg-status-danger px-4 py-2 text-sm font-medium text-white hover:bg-red-700'
                  : 'rounded-lg bg-brand-primary px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700'
              }
            >
              {confirmLabel}
            </button>
          </div>
          <Dialog.Close asChild>
            <button className="absolute right-4 top-4 text-content-tertiary hover:text-content-primary">
              <X size={16} />
            </button>
          </Dialog.Close>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
