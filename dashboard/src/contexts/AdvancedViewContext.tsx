/**
 * Memory Vault — Advanced View Context (KMV-S15.1)
 *
 * Provides a global boolean toggle that switches the Memory Explorer
 * between a non-technical default view and a full developer view.
 *
 * Default: false (non-technical)
 * Advanced: true (shows UUIDs, raw JSON, technical metadata)
 *
 * Persisted in localStorage so the preference survives page reloads.
 */
import { createContext, useContext, useState, type ReactNode } from 'react'

interface AdvancedViewContextValue {
  advanced: boolean
  setAdvanced: (v: boolean) => void
  toggle: () => void
}

const AdvancedViewContext = createContext<AdvancedViewContextValue>({
  advanced: false,
  setAdvanced: () => {},
  toggle: () => {},
})

const STORAGE_KEY = 's9nmv_advanced_view'

export function AdvancedViewProvider({ children }: { children: ReactNode }) {
  const [advanced, setAdvancedState] = useState<boolean>(() => {
    try {
      return localStorage.getItem(STORAGE_KEY) === 'true'
    } catch {
      return false
    }
  })

  const setAdvanced = (v: boolean) => {
    setAdvancedState(v)
    try { localStorage.setItem(STORAGE_KEY, String(v)) } catch { /* ignore */ }
  }

  const toggle = () => setAdvanced(!advanced)

  return (
    <AdvancedViewContext.Provider value={{ advanced, setAdvanced, toggle }}>
      {children}
    </AdvancedViewContext.Provider>
  )
}

export function useAdvancedView() {
  return useContext(AdvancedViewContext)
}
