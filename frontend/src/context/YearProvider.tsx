import { useState, type ReactNode } from 'react'
import { YearContext } from './YearContext'

export function YearProvider({ children }: { children: ReactNode }) {
  const [year, setYear] = useState(new Date().getFullYear())
  return <YearContext.Provider value={{ year, setYear }}>{children}</YearContext.Provider>
}
