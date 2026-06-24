export function formatCents(cents: number): string {
  return `$${(cents / 100).toFixed(2)}`
}

export function formatDate(dateStr: string | null | undefined): string {
  if (!dateStr) return '—'
  const d = dateStr.includes('T') ? new Date(dateStr) : new Date(dateStr + 'T00:00:00')
  return d.toLocaleDateString()
}

export const SEVERITY_COLORS: Record<string, string> = {
  red: 'bg-red-100 text-red-800 border-red-300',
  yellow: 'bg-amber-100 text-amber-800 border-amber-300',
  info: 'bg-blue-100 text-blue-800 border-blue-300',
}

export const FLAG_LABELS: Record<string, string> = {
  MISSING: 'Missing',
  STALE_PENDING: 'Stale Pending',
  DENIED: 'Denied',
  UNDERPAID: 'Underpaid',
  OVERPAID: 'Overpaid',
  UNSUBMITTED: 'Unsubmitted',
  APPROVED_ZERO_PAID: 'Zero Paid',
  VANISHED: 'Vanished',
}
