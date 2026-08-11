import { describe, expect, it } from 'vitest'

import {
  NOT_COMPUTED,
  allAbsent,
  finitePairs,
  formatNumber,
  present,
  presentCount,
  presentInterval,
  presentP,
  presentWithError,
} from './absence'

describe('present', () => {
  it('marks null as absent, never as a numeral', () => {
    const result = present(null)
    expect(result.kind).toBe('absent')
    expect(result.text).toBe(NOT_COMPUTED)
    expect(result.text).not.toMatch(/\d/)
  })

  it('treats undefined identically to null', () => {
    expect(present(undefined)).toEqual(present(null))
  })

  it('treats NaN and infinity as absent, not as printable values', () => {
    // The backend nulls these, but a payload that slipped one through must not
    // put "NaN" beside real statistics.
    for (const value of [Number.NaN, Number.POSITIVE_INFINITY, Number.NEGATIVE_INFINITY]) {
      expect(present(value).kind).toBe('absent')
    }
  })

  it('renders zero as a value, distinct from absence', () => {
    const zero = present(0)
    expect(zero.kind).toBe('value')
    expect(zero.text).toBe('0.000')
    expect(zero.text).not.toBe(NOT_COMPUTED)
  })

  it('never renders an absent value as an empty string or a dash', () => {
    const absent = present(null)
    expect(absent.text.trim()).not.toBe('')
    expect(absent.text).not.toBe('-')
    expect(absent.text).not.toBe('—')
  })

  it('carries the supplied reason onto the absence', () => {
    const result = present(null, { reason: 'the test was refused' })
    expect(result).toMatchObject({ kind: 'absent', reason: 'the test was refused' })
  })

  it('leaves reason null when the payload gave none', () => {
    expect(present(null)).toMatchObject({ reason: null })
  })

  it('formats percentages, suffixes and large magnitudes', () => {
    expect(present(0.4237, { percent: true }).text).toBe('42.4%')
    expect(present(1.5, { places: 1, suffix: ' s' }).text).toBe('1.5 s')
    expect(present(-12345.678, { places: 1 }).text).toBe('-12,346')
    expect(present(1.2e-9).text).toBe('1.20e-9')
  })
})

describe('formatNumber', () => {
  it('refuses non-finite input rather than printing NaN', () => {
    expect(() => formatNumber(Number.NaN)).toThrow(RangeError)
    expect(() => formatNumber(Number.POSITIVE_INFINITY)).toThrow(RangeError)
  })
})

describe('presentCount', () => {
  it('renders zero as a counted zero and null as absent', () => {
    expect(presentCount(0)).toMatchObject({ kind: 'value', text: '0' })
    expect(presentCount(null)).toMatchObject({ kind: 'absent', text: NOT_COMPUTED })
  })

  it('groups thousands', () => {
    expect(presentCount(1200).text).toBe('1,200')
  })
})

describe('presentP', () => {
  it('never prints an exact zero probability', () => {
    expect(presentP(0).text).toBe('< 0.001')
    expect(presentP(1e-12).text).toBe('< 0.001')
  })

  it('marks a missing p-value as absent with its reason', () => {
    expect(presentP(null, { reason: 'boundary null' })).toMatchObject({
      kind: 'absent',
      reason: 'boundary null',
    })
  })
})

describe('presentInterval', () => {
  it('is absent unless both endpoints are present', () => {
    expect(presentInterval(0.02, null).kind).toBe('absent')
    expect(presentInterval(null, 0.06).kind).toBe('absent')
    expect(presentInterval(null, null).kind).toBe('absent')
  })

  it('renders both endpoints and carries the width as the scalar', () => {
    const result = presentInterval(0.02, 0.06, { places: 2 })
    expect(result.kind).toBe('value')
    expect(result.text).toBe('0.02 to 0.06')
    if (result.kind === 'value') expect(result.value).toBeCloseTo(0.04)
  })
})

describe('presentWithError', () => {
  it('keeps the estimate and marks only the missing standard error', () => {
    const result = presentWithError(1.234, null, { places: 2 })
    expect(result.kind).toBe('value')
    expect(result.text).toBe(`1.23 ± ${NOT_COMPUTED}`)
    // Critically: never "± 0", which would invent certainty.
    expect(result.text).not.toContain('± 0')
  })

  it('is absent when the estimate itself is absent', () => {
    expect(presentWithError(null, 0.1).kind).toBe('absent')
  })

  it('renders both when both are present', () => {
    expect(presentWithError(1.2, 0.3, { places: 1 }).text).toBe('1.2 ± 0.3')
  })
})

describe('allAbsent', () => {
  it('distinguishes an all-null series from one containing a zero', () => {
    expect(allAbsent([null, undefined, Number.NaN])).toBe(true)
    expect(allAbsent([null, 0])).toBe(false)
  })
})

describe('finitePairs', () => {
  it('drops null points instead of interpolating across them', () => {
    const { points, dropped } = finitePairs([0, 1, 2, 3], [1, null, 3, Number.NaN])
    expect(points).toEqual([
      { x: 0, y: 1 },
      { x: 2, y: 3 },
    ])
    expect(dropped).toBe(2)
  })

  it('keeps zeros', () => {
    expect(finitePairs([0, 1], [0, 0]).points).toHaveLength(2)
  })
})
