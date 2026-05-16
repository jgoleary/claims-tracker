import { createContext, useContext, useState, type ReactNode } from 'react'

interface YearContextValue {
  year: number
  setYear: (year: number) => void
}

const YearContext = createContext<YearContextValue | null>(null)

export function YearProvider({ children }: { children: ReactNode }) {
  const [year, setYear] = useState(new Date().getFullYear())
  return <YearContext.Provider value={{ year, setYear }}>{children}</YearContext.Provider>
}

export function useYear() {
  const ctx = useContext(YearContext)
  if (!ctx) throw new Error('useYear must be used within YearProvider')
  return ctx
}
