import { cn } from '@/lib/utils'

interface LoadingSkeletonProps {
  className?: string
  lines?: number
}

export function LoadingSkeleton({ className, lines = 3 }: LoadingSkeletonProps) {
  return (
    <div className={cn('space-y-3', className)}>
      {Array.from({ length: lines }).map((_, i) => (
        <div
          key={i}
          className="skeleton h-4"
          style={{ width: `${80 - i * 15}%` }}
        />
      ))}
    </div>
  )
}

export function CardSkeleton() {
  return (
    <div className="rounded-lg border border-border bg-white p-6">
      <div className="skeleton mb-3 h-4 w-1/3" />
      <div className="skeleton mb-2 h-8 w-1/2" />
      <div className="skeleton h-3 w-2/3" />
    </div>
  )
}
