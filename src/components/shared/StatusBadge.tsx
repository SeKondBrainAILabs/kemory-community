import { cn } from '@/lib/utils'

type Variant = 'success' | 'warning' | 'danger' | 'neutral'

const variantStyles: Record<Variant, string> = {
  success: 'bg-green-50 text-status-success border-green-200',
  warning: 'bg-amber-50 text-status-warning border-amber-200',
  danger: 'bg-red-50 text-status-danger border-red-200',
  neutral: 'bg-gray-50 text-content-secondary border-gray-200',
}

const statusToVariant: Record<string, Variant> = {
  active: 'success',
  healthy: 'success',
  alive: 'success',
  success: 'success',
  allowed: 'success',
  ready: 'success',
  pending: 'warning',
  jit: 'warning',
  jit_pending: 'warning',
  suspended: 'warning',
  degraded: 'warning',
  denied: 'danger',
  revoked: 'danger',
  unhealthy: 'danger',
  error: 'danger',
  not_initialized: 'neutral',
}

interface StatusBadgeProps {
  status: string
  className?: string
}

export function StatusBadge({ status, className }: StatusBadgeProps) {
  const variant = statusToVariant[status.toLowerCase()] ?? 'neutral'
  return (
    <span
      className={cn(
        'inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium capitalize',
        variantStyles[variant],
        className,
      )}
    >
      {status.replace(/_/g, ' ')}
    </span>
  )
}
