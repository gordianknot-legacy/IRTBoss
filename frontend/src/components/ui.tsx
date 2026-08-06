/**
 * Layout and typographic primitives. Everything here draws from the token set
 * in `tailwind.config.js`; none of it accepts a colour.
 */

import type { ReactNode } from 'react'
import { cn } from '@/lib/format'

export function Panel({
  title,
  eyebrow,
  description,
  actions,
  children,
  className,
  id,
}: {
  title?: ReactNode
  eyebrow?: string
  description?: ReactNode
  actions?: ReactNode
  children: ReactNode
  className?: string
  id?: string
}) {
  return (
    <section
      id={id}
      className={cn(
        'rounded-lg border border-rule bg-surface shadow-card scroll-mt-8',
        className,
      )}
    >
      {(title != null || eyebrow != null || actions != null) && (
        <header className="flex flex-wrap items-start justify-between gap-3 border-b border-rule px-5 py-4">
          <div className="min-w-0">
            {eyebrow != null && <p className="eyebrow mb-1">{eyebrow}</p>}
            {title != null && (
              <h2 className="font-display text-title text-ink">{title}</h2>
            )}
            {description != null && (
              <div className="mt-2 max-w-prose text-small text-ink-muted">{description}</div>
            )}
          </div>
          {actions != null && <div className="flex shrink-0 gap-2">{actions}</div>}
        </header>
      )}
      <div className="px-5 py-4">{children}</div>
    </section>
  )
}

export type CalloutTone = 'accent' | 'attention' | 'alarm' | 'absent' | 'steady' | 'neutral'

const CALLOUT_STYLES: Record<CalloutTone, string> = {
  accent: 'border-accent/40 bg-accent-soft text-ink',
  attention: 'border-attention/40 bg-attention-soft text-ink',
  alarm: 'border-alarm/40 bg-alarm-soft text-ink',
  absent: 'border-absent/40 bg-absent-soft text-ink',
  steady: 'border-steady/40 bg-steady-soft text-ink',
  neutral: 'border-rule bg-sunken text-ink',
}

export function Callout({
  tone = 'neutral',
  title,
  children,
  className,
}: {
  tone?: CalloutTone
  title?: ReactNode
  children?: ReactNode
  className?: string
}) {
  return (
    <div className={cn('rounded border-l-4 px-4 py-3', CALLOUT_STYLES[tone], className)}>
      {title != null && <p className="mb-1 text-small font-semibold">{title}</p>}
      {children != null && <div className="max-w-prose text-small leading-relaxed">{children}</div>}
    </div>
  )
}

/**
 * The backend's `notes` arrays.
 *
 * These are first-class report content: they are written as prose for a reader
 * and every one of them explains a decision the analysis made. They are rendered
 * as a numbered list at full size, never as small print.
 */
export function Notes({
  notes,
  title = 'Notes',
  emptyMessage,
}: {
  notes: string[]
  title?: string
  emptyMessage?: string
}) {
  if (notes.length === 0) {
    return emptyMessage != null ? (
      <p className="text-small text-ink-faint">{emptyMessage}</p>
    ) : null
  }
  return (
    <div className="space-y-2">
      <p className="eyebrow">
        {title} ({notes.length})
      </p>
      <ol className="space-y-2">
        {notes.map((note, index) => (
          <li key={index} className="flex gap-3 text-small leading-relaxed text-ink">
            <span className="numeric shrink-0 pt-px text-ink-faint">{index + 1}.</span>
            <span className="max-w-prose">{note}</span>
          </li>
        ))}
      </ol>
    </div>
  )
}

export type BadgeTone = CalloutTone

const BADGE_STYLES: Record<BadgeTone, string> = {
  accent: 'bg-accent-soft text-accent',
  attention: 'bg-attention-soft text-attention',
  alarm: 'bg-alarm-soft text-alarm',
  absent: 'bg-absent-soft text-absent',
  steady: 'bg-steady-soft text-steady',
  neutral: 'bg-sunken text-ink-muted',
}

export function Badge({
  tone = 'neutral',
  children,
  className,
}: {
  tone?: BadgeTone
  children: ReactNode
  className?: string
}) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2 py-px',
        'text-micro font-semibold uppercase tracking-[0.06em]',
        BADGE_STYLES[tone],
        className,
      )}
    >
      {children}
    </span>
  )
}

export function Button({
  children,
  variant = 'primary',
  className,
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'primary' | 'secondary' | 'quiet' | 'danger'
}) {
  const styles = {
    primary: 'bg-accent text-ink-inverse hover:opacity-90',
    secondary: 'border border-rule-strong bg-surface text-ink hover:bg-sunken',
    quiet: 'text-accent hover:bg-accent-soft',
    danger: 'border border-alarm/50 bg-surface text-alarm hover:bg-alarm-soft',
  }[variant]
  return (
    <button
      className={cn(
        'inline-flex items-center justify-center gap-2 rounded px-3 py-2',
        'text-small font-semibold transition-opacity',
        'disabled:cursor-not-allowed disabled:opacity-50',
        styles,
        className,
      )}
      {...props}
    >
      {children}
    </button>
  )
}

export function Field({
  label,
  hint,
  htmlFor,
  children,
  error,
}: {
  label: string
  hint?: string
  htmlFor?: string
  children: ReactNode
  error?: string
}) {
  return (
    <label className="block space-y-1" htmlFor={htmlFor}>
      <span className="block text-small font-semibold text-ink">{label}</span>
      {hint != null && <span className="block text-small text-ink-muted">{hint}</span>}
      {children}
      {error != null && <span className="block text-small text-alarm">{error}</span>}
    </label>
  )
}

export const inputClass =
  'w-full rounded border border-rule-strong bg-raised px-3 py-2 text-body text-ink ' +
  'placeholder:text-ink-faint focus:border-accent focus:outline-none'

export function Table({
  head,
  children,
  caption,
}: {
  head: ReactNode
  children: ReactNode
  caption?: ReactNode
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-max border-collapse text-small">
        {caption != null && (
          <caption className="mb-2 text-left text-small text-ink-muted">{caption}</caption>
        )}
        <thead className="border-b border-rule-strong">{head}</thead>
        <tbody className="divide-y divide-rule">{children}</tbody>
      </table>
    </div>
  )
}

export function Th({
  children,
  align = 'right',
  title,
}: {
  children: ReactNode
  align?: 'left' | 'right'
  title?: string
}) {
  return (
    <th
      scope="col"
      title={title}
      className={cn(
        'px-3 py-2 text-micro font-semibold uppercase tracking-[0.06em] text-ink-muted',
        align === 'left' ? 'text-left' : 'text-right',
      )}
    >
      {children}
    </th>
  )
}

export function Spinner({ label }: { label: string }) {
  return (
    <p className="flex items-center gap-2 text-small text-ink-muted" role="status">
      <span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-rule border-t-accent" />
      {label}
    </p>
  )
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="rounded border border-dashed border-rule-strong px-5 py-6 text-center">
      <p className="text-body font-semibold text-ink">{title}</p>
      {children != null && (
        <div className="mx-auto mt-1 max-w-prose text-small text-ink-muted">{children}</div>
      )}
    </div>
  )
}
