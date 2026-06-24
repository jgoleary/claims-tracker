import { useRedact } from '../context/RedactContext'
import { maskName } from '../utils'

/** Renders a personal name, masked as `*** ***` when the "Hide names" toggle is on. */
export default function RedactedName({ value }: { value: string | null | undefined }) {
  const { redact } = useRedact()
  return <>{maskName(value, redact)}</>
}
