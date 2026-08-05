import { useEffect, useState, type ReactNode } from 'react'
import { RedactContext, REDACT_STORAGE_KEY } from './RedactContext'

export function RedactProvider({ children }: { children: ReactNode }) {
  const [redact, setRedact] = useState(() => localStorage.getItem(REDACT_STORAGE_KEY) === 'true')

  useEffect(() => {
    localStorage.setItem(REDACT_STORAGE_KEY, String(redact))
  }, [redact])

  return (
    <RedactContext.Provider value={{ redact, setRedact, toggle: () => setRedact((r) => !r) }}>
      {children}
    </RedactContext.Provider>
  )
}
