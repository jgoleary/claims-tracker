import { createContext, useContext } from 'react'

export interface RedactContextValue {
  redact: boolean
  setRedact: (redact: boolean) => void
  toggle: () => void
}

export const REDACT_STORAGE_KEY = 'claims-tracker-redact'

export const RedactContext = createContext<RedactContextValue | null>(null)

export function useRedact() {
  const ctx = useContext(RedactContext)
  if (!ctx) throw new Error('useRedact must be used within RedactProvider')
  return ctx
}
