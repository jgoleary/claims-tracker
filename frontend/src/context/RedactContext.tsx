import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'

interface RedactContextValue {
  redact: boolean
  setRedact: (redact: boolean) => void
  toggle: () => void
}

const STORAGE_KEY = 'claims-tracker-redact'

const RedactContext = createContext<RedactContextValue | null>(null)

export function RedactProvider({ children }: { children: ReactNode }) {
  const [redact, setRedact] = useState(() => localStorage.getItem(STORAGE_KEY) === 'true')

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, String(redact))
  }, [redact])

  return (
    <RedactContext.Provider value={{ redact, setRedact, toggle: () => setRedact((r) => !r) }}>
      {children}
    </RedactContext.Provider>
  )
}

export function useRedact() {
  const ctx = useContext(RedactContext)
  if (!ctx) throw new Error('useRedact must be used within RedactProvider')
  return ctx
}
