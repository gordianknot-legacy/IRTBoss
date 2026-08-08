/**
 * The absence layer.
 *
 * Every numeric field in the diagnostics payload is `number | null`, because
 * `analysis/serialise.to_jsonable` maps every non-finite float to `null`. A null
 * means "this statistic has no value here" — never zero, never "fine".
 *
 * So no component formats a number itself. Everything goes through `present()`,
 * which returns a discriminated union that a renderer *cannot* collapse: there
 * is no code path from `{ kind: 'absent' }` to a numeral. `formatNumber` exists
 * only for the value branch and deliberately refuses to accept a null.
 *
 * `NOT_COMPUTED` is the one marker string used across the entire product. It is
 * a word, not a dash and not an empty cell: an em-dash reads as a typographic
 * gap and an empty cell reads as a clean result, which is precisely the failure
 * this rebuild exists to remove.
 */

export const NOT_COMPUTED = 'not computed'

export interface PresentValue {
  kind: 'value'
  /** The formatted numeral. */
  text: string
  value: number
}

export interface PresentAbsent {
  kind: 'absent'
  /** Always `NOT_COMPUTED`. Never a numeral, never an empty string. */
  text: typeof NOT_COMPUTED
  /** Why, when the payload said. Shown adjacent to the marker. */
  reason: string | null
}

export type Presented = PresentValue | PresentAbsent

export interface PresentOptions {
  /** Significant-ish decimal places. Default 3. */
  places?: number
  /** Render as a percentage of 1 (0.42 -> "42.0%"). */
  percent?: boolean
  /** Appended to the numeral, e.g. " logits". */
  suffix?: string
  /**
   * Why the value is missing. Comes from a sibling field in the payload —
   * `failure_reason`, `refusal_reason`, a matching entry in `notes`.
   */
  reason?: string | null
}

/**
 * Format a finite number. Rejects null by type, and rejects NaN/Infinity at
 * runtime — a non-finite float should have been nulled by the backend, and if
 * one arrives anyway it must not be printed as "NaN" beside real statistics.
 */
export function formatNumber(value: number, options: PresentOptions = {}): string {
  if (!Number.isFinite(value)) {
    throw new RangeError('formatNumber received a non-finite value; use present() instead')
  }
  const { places = 3, percent = false, suffix = '' } = options

  if (percent) {
    return `${(value * 100).toFixed(1)}%`
  }

  const magnitude = Math.abs(value)
  let text: string
  if (value === 0) {
    text = (0).toFixed(places)
  } else if (magnitude >= 1e6 || magnitude < 1e-4) {
    text = value.toExponential(2)
  } else if (magnitude >= 1e4) {
    // Large log-likelihoods and information criteria: grouped, no decimals.
    text = Math.round(value).toLocaleString('en-GB')
  } else {
    text = value.toFixed(places)
  }
  return text + suffix
}

/**
 * The only supported way to turn a payload number into something displayable.
 *
 * `undefined` is treated exactly as `null`: a key the backend omitted and a key
 * it set to null are the same claim — no value here.
 */
export function present(
  value: number | null | undefined,
  options: PresentOptions = {},
): Presented {
  if (value == null || !Number.isFinite(value)) {
    return { kind: 'absent', text: NOT_COMPUTED, reason: options.reason ?? null }
  }
  return { kind: 'value', text: formatNumber(value, options), value }
}

/** Integers: counts, degrees of freedom, sample sizes. Grouped, never rounded. */
export function presentCount(
  value: number | null | undefined,
  options: Pick<PresentOptions, 'reason' | 'suffix'> = {},
): Presented {
  if (value == null || !Number.isFinite(value)) {
    return { kind: 'absent', text: NOT_COMPUTED, reason: options.reason ?? null }
  }
  return {
    kind: 'value',
    text: Math.round(value).toLocaleString('en-GB') + (options.suffix ?? ''),
    value,
  }
}

/**
 * p-values. Below the display floor they become "< 0.001" rather than "0.000",
 * which would read as an exact zero probability.
 */
export function presentP(
  value: number | null | undefined,
  options: Pick<PresentOptions, 'reason'> = {},
): Presented {
  if (value == null || !Number.isFinite(value)) {
    return { kind: 'absent', text: NOT_COMPUTED, reason: options.reason ?? null }
  }
  if (value < 0.001) return { kind: 'value', text: '< 0.001', value }
  return { kind: 'value', text: value.toFixed(3), value }
}

/**
 * An interval. Absent unless *both* endpoints are present: half an interval is
 * not an interval, and showing one endpoint invites reading it as a bound.
 */
export function presentInterval(
  lower: number | null | undefined,
  upper: number | null | undefined,
  options: PresentOptions = {},
): Presented {
  if (
    lower == null ||
    upper == null ||
    !Number.isFinite(lower) ||
    !Number.isFinite(upper)
  ) {
    return { kind: 'absent', text: NOT_COMPUTED, reason: options.reason ?? null }
  }
  return {
    kind: 'value',
    text: `${formatNumber(lower, options)} to ${formatNumber(upper, options)}`,
    // The value slot carries the width, which is the only scalar an interval has.
    value: upper - lower,
  }
}

/**
 * A point estimate with a standard error, as one string.
 *
 * The estimate and the SE are absent independently, so all three combinations
 * are distinct outputs. In particular an estimate with no SE is *shown*, with
 * the missing SE marked — dropping the estimate would hide a real number, and
 * printing "x ± 0" would invent certainty.
 */
export function presentWithError(
  estimate: number | null | undefined,
  standardError: number | null | undefined,
  options: PresentOptions = {},
): Presented {
  const point = present(estimate, options)
  if (point.kind === 'absent') return point
  const error = present(standardError, options)
  if (error.kind === 'absent') {
    return { ...point, text: `${point.text} ± ${NOT_COMPUTED}` }
  }
  return { ...point, text: `${point.text} ± ${error.text}` }
}

/** True when nothing in the list carries a value. Drives "no data at all" panels. */
export function allAbsent(values: (number | null | undefined)[]): boolean {
  return values.every((v) => v == null || !Number.isFinite(v))
}

/**
 * Strip nulls from a series for charting, keeping the x/y pairing intact.
 *
 * Charts must never interpolate across a gap: a line drawn through a null is a
 * value the model never produced. Callers use `dropped` to state how many points
 * are missing from a curve rather than letting the curve imply completeness.
 */
export function finitePairs(
  xs: (number | null)[],
  ys: (number | null)[],
): { points: { x: number; y: number }[]; dropped: number } {
  const points: { x: number; y: number }[] = []
  const n = Math.min(xs.length, ys.length)
  for (let i = 0; i < n; i += 1) {
    const x = xs[i]
    const y = ys[i]
    if (x != null && y != null && Number.isFinite(x) && Number.isFinite(y)) {
      points.push({ x, y })
    }
  }
  return { points, dropped: Math.max(xs.length, ys.length) - points.length }
}
