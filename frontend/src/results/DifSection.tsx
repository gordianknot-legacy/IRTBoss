import { useState } from 'react'

import type { DIFReport, DIFResult, GroupComparison } from '@/api/types'
import { modelLabel } from '@/api/types'
import { NumCell } from '@/components/Value'
import { Badge, Callout, Notes, Panel, Table, Th } from '@/components/ui'
import { present, presentP } from '@/lib/absence'
import { THRESHOLD_NOTES, difMethodLabels } from '@/lib/derive'

export function DifSection({
  id,
  dif,
  referenceModel,
}: {
  id: string
  dif: Record<string, DIFReport> | null
  referenceModel: string | null
}) {
  const columns = dif == null ? [] : Object.keys(dif)
  const [active, setActive] = useState(columns[0] ?? '')

  if (dif == null || columns.length === 0) {
    return (
      <Panel id={id} title="Differential item functioning" eyebrow="Screen">
        <Callout tone="absent" title="DIF was not screened for this run">
          No grouping variable was screened. That happens when the dataset declared no
          grouping columns, when a grouping column had fewer than two distinct groups,
          when respondents were excluded during validation so the grouping no longer
          aligns with the response matrix, or when no model converged. The run notes at
          the top of this report say which.
          <p className="mt-2">
            Nothing here should be read as “no DIF was found”. No item was examined.
          </p>
        </Callout>
      </Panel>
    )
  }

  const report = dif[active] ?? dif[columns[0] ?? '']

  return (
    <Panel
      id={id}
      title="Differential item functioning"
      eyebrow="A screen, not a verdict"
      actions={
        columns.length > 1 ? (
          <div className="flex flex-wrap gap-1 rounded bg-sunken p-1">
            {columns.map((column) => (
              <button
                key={column}
                type="button"
                onClick={() => setActive(column)}
                className={
                  'rounded px-3 py-1 text-small font-semibold transition-colors ' +
                  (active === column
                    ? 'bg-surface text-ink shadow-card'
                    : 'text-ink-muted hover:text-ink')
                }
              >
                {column}
              </button>
            ))}
          </div>
        ) : undefined
      }
    >
      <div className="space-y-5">
        <Callout tone="attention" title="What a flag here means">
          {THRESHOLD_NOTES.dif}
          <p className="mt-2">
            All of these statistics are computed against{' '}
            {referenceModel == null ? 'the reference model' : modelLabel(referenceModel)}.
            A different reference could change which items are flagged.
          </p>
        </Callout>

        {report == null ? (
          <Callout tone="absent" title="No report for this grouping variable" />
        ) : (
          <>
            <p className="text-small text-ink-muted">
              Grouping variable <strong>{active}</strong> ·{' '}
              {report.n_persons_used.toLocaleString('en-GB')} respondents used ·{' '}
              {report.comparisons.length} group comparison
              {report.comparisons.length === 1 ? '' : 's'}
            </p>

            {report.comparisons.map((comparison) => (
              <Comparison
                key={`${comparison.reference_label}-${comparison.focal_label}`}
                comparison={comparison}
              />
            ))}

            <Notes notes={report.notes} title="DIF notes" />
          </>
        )}
      </div>
    </Panel>
  )
}

function Comparison({ comparison }: { comparison: GroupComparison }) {
  const rows = comparison.items.map((item) => ({
    item,
    flaggedBy: difMethodLabels(item),
    flagged: item.flagged,
  }))
  const flaggedCount = rows.filter((r) => r.flagged).length
  const ordered = [...rows].sort((a, b) => b.flaggedBy.length - a.flaggedBy.length)

  return (
    <div className="space-y-3 rounded border border-rule bg-raised px-4 py-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h4 className="text-body font-semibold text-ink">
          {comparison.focal_label} against {comparison.reference_label}
        </h4>
        <p className="text-small text-ink-muted">
          n = {comparison.n_focal.toLocaleString('en-GB')} focal,{' '}
          {comparison.n_reference.toLocaleString('en-GB')} reference ·{' '}
          {flaggedCount} of {rows.length} items flagged by at least one method
        </p>
      </div>

      {comparison.anchor_item_ids.length > 0 && (
        <p className="text-small text-ink-muted">
          Anchor set after purification: {comparison.anchor_item_ids.join(', ')}
        </p>
      )}

      <Table
        head={
          <tr>
            <Th align="left">Item</Th>
            <Th align="left">Methods flagging</Th>
            <Th title="ETS delta scale; negative disadvantages the focal group">MH D-DIF</Th>
            <Th align="left">ETS class</Th>
            <Th title="Benjamini-Hochberg adjusted across items">MH p (adj)</Th>
            <Th title="Standardised mean difference, polytomous items">SMD</Th>
            <Th title="Total ΔR² from the nested logistic models">Logistic ΔR²</Th>
            <Th>Logistic p (adj)</Th>
            <Th>IRT-LR χ²</Th>
            <Th>IRT-LR p (adj)</Th>
          </tr>
        }
      >
        {ordered.map(({ item, flaggedBy, flagged }) => (
          <DifRow key={item.item_id} item={item} flaggedBy={flaggedBy} flagged={flagged} />
        ))}
      </Table>

      <Notes notes={comparison.notes} title="Comparison notes" />
    </div>
  )
}

function DifRow({
  item,
  flaggedBy,
  flagged,
}: {
  item: DIFResult
  flaggedBy: string[]
  flagged: boolean
}) {
  const mhAbsent = item.mantel_haenszel == null ? 'Mantel–Haenszel was not run for this item.' : null
  const mantelAbsent = item.mantel == null ? 'The Mantel test was not run for this item.' : null
  const logisticAbsent =
    item.logistic == null ? 'The logistic DIF models were not fitted for this item.' : null
  const irtAbsent =
    item.irt_lr == null ? 'The IRT likelihood-ratio test was not run for this item.' : null

  return (
    <tr className={flagged ? 'bg-attention-soft/40' : undefined}>
      <td className="numeric px-3 py-2 text-left">{item.item_id}</td>
      <td className="max-w-prose px-3 py-2 text-left">
        {flagged ? (
          <span className="flex flex-wrap gap-1">
            {flaggedBy.map((method) => (
              <Badge key={method} tone="attention">
                {method}
              </Badge>
            ))}
          </span>
        ) : (
          <span className="text-small text-ink-faint">no method flagged this item</span>
        )}
        {item.notes.length > 0 && (
          <p className="mt-1 text-small text-ink-muted">{item.notes.join(' ')}</p>
        )}
      </td>
      <NumCell
        presented={present(item.mantel_haenszel?.d_dif, { places: 2, reason: mhAbsent })}
      />
      <td className="px-3 py-2 text-left">
        {item.mantel_haenszel?.ets_class != null ? (
          <span className="numeric">{item.mantel_haenszel.ets_class}</span>
        ) : (
          <span className="text-micro font-semibold uppercase tracking-wide text-absent">
            ∅ not computed
          </span>
        )}
      </td>
      <NumCell presented={presentP(item.mh_p_adjusted, { reason: mhAbsent })} />
      <NumCell
        presented={present(item.mantel?.smd_standardised, {
          places: 3,
          reason:
            mantelAbsent ??
            'The ETS A/B/C classification does not apply to polytomous items; judge them on this figure.',
        })}
      />
      <NumCell
        presented={present(item.logistic?.total_delta_r2, { places: 4, reason: logisticAbsent })}
      />
      <NumCell presented={presentP(item.logistic_p_adjusted, { reason: logisticAbsent })} />
      <NumCell presented={present(item.irt_lr?.chi_square, { places: 2, reason: irtAbsent })} />
      <NumCell presented={presentP(item.irt_p_adjusted, { reason: irtAbsent })} />
    </tr>
  )
}
