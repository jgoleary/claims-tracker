import { createContext, useContext } from 'react'

export interface YearContextValue {
  year: number
  setYear: (year: number) => void
}

export const YearContext = createContext<YearContextValue | null>(null)

export function useYear() {
  const ctx = useContext(YearContext)
  if (!ctx) throw new Error('useYear must be used within YearProvider')
  return ctx
}
