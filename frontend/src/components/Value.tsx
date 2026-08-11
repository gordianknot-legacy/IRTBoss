/**
 * The only component in the product that renders a statistic.
 *
 * It takes a `Presented` (from `lib/absence`), never a raw number, so there is
 * no way to render a payload field without having gone through the null check.
 * An absent value gets its own colour, its own weight, and the literal words
 * "not computed" — visually distinct from a zero, from a dash, and from an empty
 * cell. Where the payload carries a reason, it is attached as a title and, in
 * table rows, printed underneath.
 */

import type { Presented } from '@/lib/absence'
import { cn } from '@/lib/format'

export function Value({
  presented,
  className,
  emphasis = 'normal',
}: {
  presented: Presented
  className?: string
  emphasis?: 'normal' | 'strong'
}) {
  if (presented.kind === 'absent') {
    return (
      <span
        className={cn(
          'inline-flex items-baseline gap-1 rounded-sm bg-absent-soft px-1 py-px',
          'font-sans text-micro font-semibold uppercase tracking-[0.06em] text-absent',
          className,
        )}
        title={presented.reason ?? 'This statistic has no value here. It is not zero.'}
        data-absent="true"
      >
        <span aria-hidden="true">∅</span>
        <span>{presented.text}</span>
      </span>
    )
  }
  return (
    <span
      className={cn('numeric', emphasis === 'strong' && 'font-semibold text-body', className)}
      data-absent="false"
    >
      {presented.text}
    </span>
  )
}

/**
 * A labelled statistic. The reason for an absence is printed, not just hovered:
 * a tooltip is not a place to put the explanation of why a number is missing.
 */
export function Stat({
  label,
  presented,
  hint,
}: {
  label: string
  presented: Presented
  hint?: string
}) {
  return (
    <div className="flex flex-col gap-1 border-l-2 border-rule pl-3">
      <span className="eyebrow">{label}</span>
      <Value presented={presented} emphasis="strong" className="text-lede" />
      {presented.kind === 'absent' && presented.reason != null && (
        <p className="max-w-prose text-small text-ink-muted">{presented.reason}</p>
      )}
      {hint != null && <p className="max-w-prose text-small text-ink-faint">{hint}</p>}
    </div>
  )
}

/** Table cell wrapper: keeps every numeric column right-aligned and monospaced. */
export function NumCell({
  presented,
  className,
}: {
  presented: Presented
  className?: string
}) {
  return (
    <td className={cn('px-3 py-2 text-right align-baseline', className)}>
      <Value presented={presented} />
    </td>
  )
}
