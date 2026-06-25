export function formatCents(cents: number): string {
  return `$${(cents / 100).toFixed(2)}`
}

/** Mask a personal name for demos. When `redact`, each whitespace-separated token
 *  becomes `***` (e.g. "Nolan O'leary" → "*** ***"); otherwise the value is unchanged. */
export function maskName(value: string | null | undefined, redact: boolean): string {
  if (!value) return value ?? ''
  if (!redact) return value
  return value.trim().split(/\s+/).map(() => '***').join(' ')
}

/** JS mirror of the backend `matching.normalize()` so provider lookups key
 *  identically: lowercase, collapse whitespace, strip non-alphanumerics. */
export const normalizeProvider = (s: string) =>
  s.toLowerCase().trim().replace(/\s+/g, ' ').replace(/[^a-z0-9 ]/g, '')

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

export function computeExpected(
  billedCents: number,
  deductibleRemainingCents: number,
  oopRemainingCents: number,
  coinsurancePct: number,
): number {
  const deductibleApplied = Math.min(billedCents, Math.max(0, deductibleRemainingCents))
  const afterDeductible = billedCents - deductibleApplied
  const memberOop = Math.min(
    deductibleApplied + Math.round(afterDeductible * coinsurancePct),
    Math.max(0, oopRemainingCents),
  )
  return billedCents - memberOop
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
