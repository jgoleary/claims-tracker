import { SEVERITY_COLORS, FLAG_LABELS } from '../utils'

interface Props {
  flag: string
  severity: string
}

export default function AlertBadge({ flag, severity }: Props) {
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium border ${SEVERITY_COLORS[severity] ?? 'bg-gray-100 text-gray-700'}`}>
      {FLAG_LABELS[flag] ?? flag}
    </span>
  )
}
