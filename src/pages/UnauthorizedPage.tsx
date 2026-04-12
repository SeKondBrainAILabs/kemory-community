import { useNavigate } from 'react-router-dom'
import { ShieldOff, ArrowLeft } from 'lucide-react'

export function UnauthorizedPage() {
  const navigate = useNavigate()

  return (
    <div className="flex min-h-screen items-center justify-center bg-surface-primary">
      <div className="max-w-md px-4 text-center">
        <div className="mb-4 inline-flex h-16 w-16 items-center justify-center rounded-full bg-red-100 text-red-600">
          <ShieldOff size={32} />
        </div>
        <h1 className="mb-2 text-2xl font-bold text-content-primary">Access Denied</h1>
        <p className="mb-6 text-sm text-content-secondary">
          You don't have the required permissions to access this page.
          Contact your administrator if you believe this is an error.
        </p>
        <button
          onClick={() => navigate('/')}
          className="inline-flex items-center gap-2 rounded-lg bg-brand-primary px-4 py-2 text-sm font-medium text-white hover:bg-brand-primary/90 transition-colors"
        >
          <ArrowLeft size={16} />
          Back to Dashboard
        </button>
      </div>
    </div>
  )
}
