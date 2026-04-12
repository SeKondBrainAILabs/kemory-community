import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { Brain, LogIn } from 'lucide-react'
import { useAuth } from '@/context/AuthContext'

export function LoginPage() {
  const { isAuthenticated, isLoading, error, login } = useAuth()
  const navigate = useNavigate()

  useEffect(() => {
    if (isAuthenticated) {
      navigate('/', { replace: true })
    }
  }, [isAuthenticated, navigate])

  if (isLoading) {
    return (
      <div className="flex h-screen items-center justify-center bg-surface-primary">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-brand-primary border-t-transparent" />
      </div>
    )
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-gradient-to-br from-slate-50 to-slate-100">
      <div className="w-full max-w-md px-4">
        <div className="rounded-2xl border border-border bg-white p-8 shadow-lg">
          {/* Logo & Branding */}
          <div className="mb-8 flex flex-col items-center">
            <div className="mb-4 flex h-16 w-16 items-center justify-center rounded-2xl bg-brand-primary text-white shadow-md">
              <Brain size={32} />
            </div>
            <h1 className="text-2xl font-bold text-content-primary">S9N Memory Vault</h1>
            <p className="mt-1 text-sm text-content-secondary">Memory Vault Control Plane</p>
          </div>

          {/* Error message */}
          {error && (
            <div className="mb-6 rounded-lg border border-red-200 bg-red-50 p-3 text-center text-sm text-red-600">
              {error}
            </div>
          )}

          {/* Sign in button */}
          <button
            onClick={() => login()}
            className="flex w-full items-center justify-center gap-2 rounded-lg bg-brand-primary px-4 py-3 text-sm font-medium text-white shadow-sm transition-colors hover:bg-brand-primary/90 focus:outline-none focus:ring-2 focus:ring-brand-primary focus:ring-offset-2"
          >
            <LogIn size={18} />
            Sign in
          </button>

          <p className="mt-6 text-center text-xs text-content-tertiary">
            Secure access to your memory vault
          </p>
        </div>
      </div>
    </div>
  )
}
