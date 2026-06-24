import { describe, it, expect } from 'vitest'
import { computeExpected, maskName } from './utils'

describe('maskName', () => {
  it('returns the value unchanged when redact is off', () => {
    expect(maskName("Nolan O'leary", false)).toBe("Nolan O'leary")
  })

  it('masks each token when redact is on', () => {
    expect(maskName("Nolan O'leary", true)).toBe('*** ***')
  })

  it('masks a single-word name to one token', () => {
    expect(maskName('Nolan', true)).toBe('***')
  })

  it('masks a three-word name to three tokens', () => {
    expect(maskName('Joyful Behavior Therapy', true)).toBe('*** *** ***')
  })

  it('handles null/empty values', () => {
    expect(maskName(null, true)).toBe('')
    expect(maskName('', true)).toBe('')
  })
})

describe('computeExpected', () => {
  it('routes the whole bill to the deductible when deductible remaining covers it', () => {
    expect(computeExpected(100000, 200000, 9999999, 0.3)).toBe(0)
  })

  it('applies deductible then coinsurance', () => {
    // $570 billed, $200 deductible remaining, 30% coinsurance → $259 expected
    expect(computeExpected(57000, 20000, 9999999, 0.3)).toBe(25900)
  })

  it('caps member cost at the out-of-pocket remaining', () => {
    // member would owe $311 but only $50 OOP remains → plan pays the rest
    expect(computeExpected(57000, 20000, 5000, 0.3)).toBe(52000)
  })
})
