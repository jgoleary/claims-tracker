import { describe, it, expect } from 'vitest'
import { computeExpected } from './utils'

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
