import { Navigate, useLocation } from 'react-router-dom'
import { useAuth } from '@/context/AuthContext'
import { Loader2 } from 'lucide-react'

interface Props {
  children: React.ReactNode
  requiredRole?: string
}

function LoadingScreen({ message = 'Loading...' }: { message?: string }) {
  return (
    <div className="flex h-screen w-screen items-center justify-center bg-surface-primary">
      <div className="flex flex-col items-center gap-3">
        <Loader2 className="h-8 w-8 animate-spin text-brand-primary" />
        <p className="text-sm text-content-secondary">{message}</p>
      </div>
    </div>
  )
}

export function RequireAuth({ children, requiredRole }: Props) {
  const { isAuthenticated, isLoading, hasRole, error } = useAuth()
  const location = useLocation()

  if (isLoading) {
    return <LoadingScreen message="Checking authentication..." />
  }

  if (error) {
    return (
      <div className="flex h-screen w-screen items-center justify-center bg-surface-primary">
        <div className="max-w-md rounded-lg border border-red-200 bg-red-50 p-6 text-center">
          <h2 className="mb-2 text-lg font-semibold text-red-800">Authentication Error</h2>
          <p className="text-sm text-red-600">{error}</p>
        </div>
      </div>
    )
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" state={{ from: location }} replace />
  }

  if (requiredRole && !hasRole(requiredRole)) {
    return <Navigate to="/unauthorized" state={{ from: location }} replace />
  }

  return <>{children}</>
}
