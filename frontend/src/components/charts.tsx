/**
 * Charts, in plain SVG.
 *
 * No charting library and no d3: every figure here is a polyline, a rect or a
 * circle over a linear scale, and a dependency that draws those would be heavier
 * than the code it replaced.
 *
 * Three rules the whole file is built to keep:
 *
 * **No line is drawn through a null.** A series arrives as `(number | null)[]`
 * and is split into contiguous finite runs; each run is its own `<polyline>`.
 * Interpolating over a gap would draw a value the model never produced, which is
 * the charting form of the empty-cell defect this product exists to remove. The
 * number of dropped points is reported under the figure.
 *
 * **One y-axis, ever.** Test information and conditional standard error live on
 * different scales, so they are two figures, not one figure with two axes.
 *
 * **Colour never carries identity alone.** Two-series figures always get a
 * legend and, where there is room, a direct label at the end of each line.
 */

import { useId, useMemo, useState } from 'react'
import { cn } from '@/lib/format'

const SERIES_CLASS = ['stroke-series-1', 'stroke-series-2'] as const
const SERIES_FILL = ['fill-series-1', 'fill-series-2'] as const
const SERIES_TEXT = ['text-series-1', 'text-series-2'] as const

export interface Series {
  label: string
  /** Aligned with `x`. Nulls are gaps, never zeros. */
  y: (number | null)[]
  /** Dashed lines read as "modelled" rather than "observed". */
  dashed?: boolean
}

interface Scale {
  (value: number): number
}

function linearScale(domain: [number, number], range: [number, number]): Scale {
  const [d0, d1] = domain
  const [r0, r1] = range
  const span = d1 - d0
  if (span === 0) return () => (r0 + r1) / 2
  return (value: number) => r0 + ((value - d0) / span) * (r1 - r0)
}

function niceTicks(min: number, max: number, count = 5): number[] {
  if (!Number.isFinite(min) || !Number.isFinite(max) || min === max) return [min]
  const raw = (max - min) / count
  const magnitude = 10 ** Math.floor(Math.log10(raw))
  const step = [1, 2, 2.5, 5, 10].map((m) => m * magnitude).find((s) => s >= raw) ?? magnitude * 10
  const start = Math.ceil(min / step) * step
  const out: number[] = []
  for (let v = start; v <= max + step * 1e-9; v += step) out.push(Number(v.toFixed(10)))
  return out
}

function tickLabel(value: number): string {
  const magnitude = Math.abs(value)
  if (magnitude !== 0 && (magnitude >= 1e5 || magnitude < 1e-3)) return value.toExponential(1)
  if (Number.isInteger(value)) return String(value)
  return value.toFixed(magnitude < 1 ? 2 : 1)
}

/** Contiguous runs of finite points. The gaps between runs are never bridged. */
function runsOf(x: number[], y: (number | null)[]): { x: number; y: number }[][] {
  const runs: { x: number; y: number }[][] = []
  let current: { x: number; y: number }[] = []
  for (let i = 0; i < x.length; i += 1) {
    const xi = x[i]
    const yi = y[i]
    if (xi != null && yi != null && Number.isFinite(xi) && Number.isFinite(yi)) {
      current.push({ x: xi, y: yi })
    } else if (current.length > 0) {
      runs.push(current)
      current = []
    }
  }
  if (current.length > 0) runs.push(current)
  return runs
}

function Figure({
  title,
  caption,
  footnote,
  children,
}: {
  title: string
  caption?: string
  footnote?: string
  children: React.ReactNode
}) {
  return (
    <figure className="space-y-2">
      <figcaption>
        <p className="text-small font-semibold text-ink">{title}</p>
        {caption != null && <p className="max-w-prose text-small text-ink-muted">{caption}</p>}
      </figcaption>
      {children}
      {footnote != null && <p className="max-w-prose text-small text-ink-faint">{footnote}</p>}
    </figure>
  )
}

function Legend({ series }: { series: Series[] }) {
  if (series.length < 2) return null
  return (
    <ul className="flex flex-wrap gap-4">
      {series.map((s, i) => (
        <li key={s.label} className="flex items-center gap-2 text-small text-ink-muted">
          <svg width="18" height="8" aria-hidden="true">
            <line
              x1="0"
              y1="4"
              x2="18"
              y2="4"
              strokeWidth="2"
              strokeDasharray={s.dashed === true ? '4 3' : undefined}
              className={SERIES_CLASS[i % SERIES_CLASS.length]}
            />
          </svg>
          {s.label}
        </li>
      ))}
    </ul>
  )
}

/* ---------------------------------------------------------------------- *
 * Line chart
 * ---------------------------------------------------------------------- */

const PAD = { top: 12, right: 56, bottom: 34, left: 52 }

export function LineChart({
  title,
  caption,
  x,
  xLabel,
  yLabel,
  series,
  height = 220,
  /** Horizontal reference lines, e.g. a standard-error bar at 0.50. */
  markers = [],
  formatY = tickLabel,
}: {
  title: string
  caption?: string
  x: number[]
  xLabel: string
  yLabel: string
  series: Series[]
  height?: number
  markers?: { value: number; label: string }[]
  formatY?: (value: number) => string
}) {
  const width = 640
  const [hover, setHover] = useState<number | null>(null)
  const clipId = useId()

  const allRuns = useMemo(() => series.map((s) => runsOf(x, s.y)), [x, series])
  const dropped = useMemo(
    () => series.reduce((sum, s) => sum + s.y.filter((v) => v == null || !Number.isFinite(v)).length, 0),
    [series],
  )

  const values = allRuns.flat(2).map((p) => p.y)
  const referenceValues = markers.map((m) => m.value)

  if (values.length === 0) {
    return (
      <Figure title={title} caption={caption}>
        <div className="rounded border border-dashed border-absent bg-absent-soft px-4 py-6 text-center text-small text-absent">
          Not computed — this curve has no finite points, so there is nothing to plot.
        </div>
      </Figure>
    )
  }

  const xs = allRuns.flat(2).map((p) => p.x)
  const xDomain: [number, number] = [Math.min(...xs), Math.max(...xs)]
  const yMin = Math.min(...values, ...referenceValues)
  const yMax = Math.max(...values, ...referenceValues)
  const padY = (yMax - yMin) * 0.08 || 0.5
  const yDomain: [number, number] = [yMin - padY, yMax + padY]

  const sx = linearScale(xDomain, [PAD.left, width - PAD.right])
  const sy = linearScale(yDomain, [height - PAD.bottom, PAD.top])

  const xTicks = niceTicks(xDomain[0], xDomain[1], 6)
  const yTicks = niceTicks(yDomain[0], yDomain[1], 5)

  // Nearest sample to the pointer, for the crosshair readout.
  const hoverIndex =
    hover == null
      ? null
      : x.reduce<number | null>((best, value, index) => {
          if (value == null || !Number.isFinite(value)) return best
          if (best == null) return index
          const bx = x[best]
          if (bx == null) return index
          return Math.abs(value - hover) < Math.abs(bx - hover) ? index : best
        }, null)

  const hoverX = hoverIndex == null ? null : x[hoverIndex]

  return (
    <Figure
      title={title}
      caption={caption}
      footnote={
        dropped > 0
          ? `${dropped} of ${x.length * series.length} points had no value and are omitted. ` +
            'The line breaks at each gap rather than crossing it.'
          : undefined
      }
    >
      <Legend series={series} />
      <div className="relative">
        <svg
          viewBox={`0 0 ${width} ${height}`}
          className="w-full"
          role="img"
          aria-label={`${title}. ${yLabel} against ${xLabel}.`}
          onPointerMove={(event) => {
            const rect = event.currentTarget.getBoundingClientRect()
            const px = ((event.clientX - rect.left) / rect.width) * width
            const t = (px - PAD.left) / (width - PAD.right - PAD.left)
            setHover(xDomain[0] + t * (xDomain[1] - xDomain[0]))
          }}
          onPointerLeave={() => setHover(null)}
        >
          <clipPath id={clipId}>
            <rect
              x={PAD.left}
              y={PAD.top}
              width={width - PAD.right - PAD.left}
              height={height - PAD.bottom - PAD.top}
            />
          </clipPath>

          {yTicks.map((t) => (
            <g key={`y${t}`}>
              <line
                x1={PAD.left}
                x2={width - PAD.right}
                y1={sy(t)}
                y2={sy(t)}
                className="stroke-rule"
                strokeWidth="1"
              />
              <text
                x={PAD.left - 8}
                y={sy(t)}
                textAnchor="end"
                dominantBaseline="middle"
                className="fill-ink-faint text-[10px]"
              >
                {formatY(t)}
              </text>
            </g>
          ))}

          {xTicks.map((t) => (
            <text
              key={`x${t}`}
              x={sx(t)}
              y={height - PAD.bottom + 16}
              textAnchor="middle"
              className="fill-ink-faint text-[10px]"
            >
              {tickLabel(t)}
            </text>
          ))}

          {markers.map((m) => (
            <g key={m.label} clipPath={`url(#${clipId})`}>
              <line
                x1={PAD.left}
                x2={width - PAD.right}
                y1={sy(m.value)}
                y2={sy(m.value)}
                className="stroke-ink-faint"
                strokeWidth="1"
                strokeDasharray="2 4"
              />
              <text
                x={width - PAD.right - 4}
                y={sy(m.value) - 4}
                textAnchor="end"
                className="fill-ink-faint text-[10px]"
              >
                {m.label}
              </text>
            </g>
          ))}

          {allRuns.map((runs, index) =>
            runs.map((run, r) => (
              <polyline
                key={`${index}-${r}`}
                clipPath={`url(#${clipId})`}
                fill="none"
                strokeWidth="2"
                strokeLinejoin="round"
                strokeLinecap="round"
                strokeDasharray={series[index]?.dashed === true ? '5 4' : undefined}
                className={SERIES_CLASS[index % SERIES_CLASS.length]}
                points={run.map((p) => `${sx(p.x)},${sy(p.y)}`).join(' ')}
              />
            )),
          )}

          {/* Direct labels at the right-hand end of each series. */}
          {allRuns.map((runs, index) => {
            const last = runs.at(-1)?.at(-1)
            if (last == null || series.length < 2) return null
            return (
              <text
                key={`label-${index}`}
                x={width - PAD.right + 6}
                y={sy(last.y)}
                dominantBaseline="middle"
                className={cn('text-[10px] font-semibold', SERIES_TEXT[index % SERIES_TEXT.length])}
              >
                {series[index]?.label.slice(0, 8)}
              </text>
            )
          })}

          {hoverX != null && (
            <line
              x1={sx(hoverX)}
              x2={sx(hoverX)}
              y1={PAD.top}
              y2={height - PAD.bottom}
              className="stroke-ink-faint"
              strokeWidth="1"
            />
          )}
          {hoverIndex != null &&
            series.map((s, index) => {
              const value = s.y[hoverIndex]
              if (value == null || !Number.isFinite(value) || hoverX == null) return null
              return (
                <circle
                  key={`dot-${index}`}
                  cx={sx(hoverX)}
                  cy={sy(value)}
                  r="4"
                  className={cn(SERIES_FILL[index % SERIES_FILL.length], 'stroke-surface')}
                  strokeWidth="2"
                />
              )
            })}

          <line
            x1={PAD.left}
            x2={width - PAD.right}
            y1={height - PAD.bottom}
            y2={height - PAD.bottom}
            className="stroke-rule-strong"
            strokeWidth="1"
          />
          <text
            x={(PAD.left + width - PAD.right) / 2}
            y={height - 2}
            textAnchor="middle"
            className="fill-ink-muted text-[10px]"
          >
            {xLabel}
          </text>
          <text
            x={12}
            y={PAD.top + 4}
            className="fill-ink-muted text-[10px]"
          >
            {yLabel}
          </text>
        </svg>

        {hoverIndex != null && hoverX != null && (
          <div className="pointer-events-none absolute right-2 top-2 rounded border border-rule bg-raised px-2 py-1 text-micro shadow-card">
            <p className="font-mono text-ink-muted">
              {xLabel} {tickLabel(hoverX)}
            </p>
            {series.map((s, index) => {
              const value = s.y[hoverIndex]
              return (
                <p key={s.label} className="font-mono text-ink">
                  <span className={SERIES_TEXT[index % SERIES_TEXT.length]}>■</span> {s.label}{' '}
                  {value == null || !Number.isFinite(value) ? (
                    <span className="text-absent">not computed</span>
                  ) : (
                    formatY(value)
                  )}
                </p>
              )
            })}
          </div>
        )}
      </div>
    </Figure>
  )
}

/* ---------------------------------------------------------------------- *
 * Interval (forest) chart — a point estimate with an uncertainty bar
 * ---------------------------------------------------------------------- */

export interface IntervalRow {
  label: string
  value: number | null
  /** Half-width of the bar. Null means the uncertainty was not estimated. */
  error: number | null
  /** Rendered muted; used for models excluded from the ranking. */
  muted?: boolean
}

export function IntervalChart({
  title,
  caption,
  rows,
  valueLabel,
}: {
  title: string
  caption?: string
  rows: IntervalRow[]
  valueLabel: string
}) {
  const finite = rows.filter((r) => r.value != null && Number.isFinite(r.value))
  if (finite.length === 0) {
    return (
      <Figure title={title} caption={caption}>
        <div className="rounded border border-dashed border-absent bg-absent-soft px-4 py-6 text-center text-small text-absent">
          Not computed — no model produced a value on this criterion.
        </div>
      </Figure>
    )
  }

  const lows = finite.map((r) => (r.value ?? 0) - (r.error ?? 0))
  const highs = finite.map((r) => (r.value ?? 0) + (r.error ?? 0))
  const min = Math.min(...lows)
  const max = Math.max(...highs)
  const pad = (max - min) * 0.12 || 1
  const width = 640
  const rowHeight = 34
  const height = rows.length * rowHeight + 30
  const left = 150
  const sx = linearScale([min - pad, max + pad], [left, width - 24])
  const ticks = niceTicks(min - pad, max + pad, 5)

  return (
    <Figure
      title={title}
      caption={caption}
      footnote={
        'Bars are ± one standard error of the total across folds. Overlapping bars mean the ' +
        'criterion does not separate those models. A row with no bar had no uncertainty estimate; ' +
        'its position carries no margin.'
      }
    >
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="w-full"
        role="img"
        aria-label={`${title}. ${valueLabel} per model with uncertainty.`}
      >
        {ticks.map((t) => (
          <g key={t}>
            <line
              x1={sx(t)}
              x2={sx(t)}
              y1={4}
              y2={height - 26}
              className="stroke-rule"
              strokeWidth="1"
            />
            <text
              x={sx(t)}
              y={height - 12}
              textAnchor="middle"
              className="fill-ink-faint text-[10px]"
            >
              {tickLabel(t)}
            </text>
          </g>
        ))}

        {rows.map((row, index) => {
          const y = index * rowHeight + rowHeight / 2
          if (row.value == null || !Number.isFinite(row.value)) {
            return (
              <g key={row.label}>
                <text x={left - 10} y={y} textAnchor="end" dominantBaseline="middle" className="fill-ink-muted text-[11px]">
                  {row.label}
                </text>
                <text x={left + 4} y={y} dominantBaseline="middle" className="fill-absent text-[10px] font-semibold uppercase tracking-wide">
                  ∅ not computed
                </text>
              </g>
            )
          }
          const cx = sx(row.value)
          return (
            <g key={row.label} opacity={row.muted === true ? 0.5 : 1}>
              <text x={left - 10} y={y} textAnchor="end" dominantBaseline="middle" className="fill-ink text-[11px]">
                {row.label}
              </text>
              {row.error != null && Number.isFinite(row.error) ? (
                <>
                  <line
                    x1={sx(row.value - row.error)}
                    x2={sx(row.value + row.error)}
                    y1={y}
                    y2={y}
                    className="stroke-series-1"
                    strokeWidth="2"
                    strokeLinecap="round"
                  />
                  <line x1={sx(row.value - row.error)} x2={sx(row.value - row.error)} y1={y - 5} y2={y + 5} className="stroke-series-1" strokeWidth="2" />
                  <line x1={sx(row.value + row.error)} x2={sx(row.value + row.error)} y1={y - 5} y2={y + 5} className="stroke-series-1" strokeWidth="2" />
                </>
              ) : (
                <text x={cx + 12} y={y - 8} className="fill-absent text-[9px] font-semibold uppercase tracking-wide">
                  no uncertainty estimate
                </text>
              )}
              <circle cx={cx} cy={y} r="5" className="fill-series-1 stroke-surface" strokeWidth="2" />
            </g>
          )
        })}
      </svg>
    </Figure>
  )
}

/* ---------------------------------------------------------------------- *
 * Distribution strip — person-score percentiles
 * ---------------------------------------------------------------------- */

export function PercentileStrip({
  title,
  caption,
  percentiles,
  minimum,
  maximum,
  mean,
}: {
  title: string
  caption?: string
  percentiles: Record<string, number | null>
  minimum: number | null
  maximum: number | null
  mean: number | null
}) {
  const get = (key: string) => {
    const v = percentiles[key]
    return v != null && Number.isFinite(v) ? v : null
  }
  const p5 = get('5')
  const p25 = get('25')
  const p50 = get('50')
  const p75 = get('75')
  const p95 = get('95')

  const anchors = [minimum, maximum, p5, p25, p50, p75, p95].filter(
    (v): v is number => v != null && Number.isFinite(v),
  )
  if (anchors.length < 2 || p25 == null || p75 == null) {
    return (
      <Figure title={title} caption={caption}>
        <div className="rounded border border-dashed border-absent bg-absent-soft px-4 py-6 text-small text-absent">
          Not computed — the score summary does not carry enough quantiles to draw a distribution.
        </div>
      </Figure>
    )
  }

  const width = 640
  const height = 96
  const min = Math.min(...anchors)
  const max = Math.max(...anchors)
  const pad = (max - min) * 0.08 || 0.5
  const sx = linearScale([min - pad, max + pad], [40, width - 40])
  const mid = 44
  const ticks = niceTicks(min - pad, max + pad, 6)

  return (
    <Figure
      title={title}
      caption={caption}
      footnote="Box spans the 25th to 75th percentile; whiskers reach the 5th and 95th. Respondents who could not be scored are excluded and counted separately — they are not placed at the prior mean."
    >
      <svg viewBox={`0 0 ${width} ${height}`} className="w-full" role="img" aria-label={title}>
        {ticks.map((t) => (
          <text key={t} x={sx(t)} y={height - 8} textAnchor="middle" className="fill-ink-faint text-[10px]">
            {tickLabel(t)}
          </text>
        ))}
        <line x1={40} x2={width - 40} y1={mid} y2={mid} className="stroke-rule" strokeWidth="1" />
        {p5 != null && p95 != null && (
          <line x1={sx(p5)} x2={sx(p95)} y1={mid} y2={mid} className="stroke-series-1" strokeWidth="2" />
        )}
        <rect
          x={sx(p25)}
          y={mid - 14}
          width={Math.max(sx(p75) - sx(p25), 2)}
          height={28}
          rx="3"
          className="fill-series-1/25 stroke-series-1"
          strokeWidth="2"
        />
        {p50 != null && (
          <line x1={sx(p50)} x2={sx(p50)} y1={mid - 16} y2={mid + 16} className="stroke-series-1" strokeWidth="3" />
        )}
        {mean != null && Number.isFinite(mean) && (
          <>
            <circle cx={sx(mean)} cy={mid} r="4" className="fill-series-2 stroke-surface" strokeWidth="2" />
            <text x={sx(mean)} y={mid - 22} textAnchor="middle" className="fill-series-2 text-[10px] font-semibold">
              mean
            </text>
          </>
        )}
        {p50 != null && (
          <text x={sx(p50)} y={mid + 30} textAnchor="middle" className="fill-ink-muted text-[10px]">
            median
          </text>
        )}
      </svg>
    </Figure>
  )
}

/* ---------------------------------------------------------------------- *
 * Bar list — used for the eigenvalue scree comparison and ΔR² style rows
 * ---------------------------------------------------------------------- */

export function ScreePlot({
  eigenvalues,
}: {
  eigenvalues: { component: number; observed: number | null; random_p95: number | null }[]
}) {
  const x = eigenvalues.map((e) => e.component)
  return (
    <LineChart
      title="Parallel analysis"
      caption="Observed eigenvalues of the polychoric matrix against the 95th percentile of eigenvalues from data with the same marginals and no common factor. A component is retained while the observed value stays above the reference."
      x={x}
      xLabel="component"
      yLabel="eigenvalue"
      series={[
        { label: 'observed', y: eigenvalues.map((e) => e.observed) },
        { label: 'random 95th percentile', y: eigenvalues.map((e) => e.random_p95), dashed: true },
      ]}
    />
  )
}
