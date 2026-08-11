import type { SampleSummary, ValidationSummary } from '@/api/types'
import { Stat } from '@/components/Value'
import { Badge, Callout, Table, Th } from '@/components/ui'
import { present, presentCount } from '@/lib/absence'

export function SampleSection({
  sample,
  validation,
}: {
  sample: SampleSummary
  validation: ValidationSummary
}) {
  const recodedItems = Object.entries(validation.recoding)
  const nonConsecutive = recodedItems.filter(([, mapping]) => {
    const codes = Object.keys(mapping).map(Number)
    return codes.some((c, i) => c !== i)
  })

  return (
    <div className="space-y-5">
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stat
          label="Respondents analysed"
          presented={presentCount(sample.n_persons)}
          hint={
            validation.n_persons_dropped > 0
              ? `${validation.n_persons_dropped} more answered no items and were excluded.`
              : 'Everyone who answered at least one item.'
          }
        />
        <Stat label="Items modelled" presented={presentCount(sample.n_items)} />
        <Stat
          label="Missing responses"
          presented={present(sample.missing_rate, { percent: true })}
          hint="Handled by full-information maximum likelihood. Nothing is imputed."
        />
        <div className="flex flex-col gap-1 border-l-2 border-rule pl-3">
          <span className="eyebrow">Response format</span>
          <span className="text-lede font-semibold">
            {sample.is_polytomous ? 'Polytomous' : 'Dichotomous'}
          </span>
          <span className="text-small text-ink-muted">
            {sample.n_categories.length === 0
              ? 'category counts not recorded'
              : `${Math.min(...sample.n_categories)}–${Math.max(...sample.n_categories)} categories per item`}
          </span>
        </div>
      </div>

      {validation.dropped_items.length > 0 && (
        <div className="space-y-2">
          <p className="eyebrow">
            Columns excluded during validation ({validation.dropped_items.length})
          </p>
          <p className="max-w-prose text-small text-ink-muted">
            These take no part in any statistic below. Nothing was coerced into a
            fittable shape to keep it.
          </p>
          <Table
            head={
              <tr>
                <Th align="left">Column</Th>
                <Th align="left">Why it was excluded</Th>
              </tr>
            }
          >
            {validation.dropped_items.map((item) => (
              <tr key={item.item_id}>
                <td className="numeric px-3 py-2 text-left">{item.item_id}</td>
                <td className="max-w-prose px-3 py-2 text-left text-ink-muted">
                  {item.reason}
                </td>
              </tr>
            ))}
          </Table>
        </div>
      )}

      {nonConsecutive.length > 0 && (
        <Callout tone="attention" title={`${nonConsecutive.length} item(s) were renumbered`}>
          Their response codes were not consecutive, so unused middle categories were
          removed rather than estimated:{' '}
          {nonConsecutive.slice(0, 6).map(([itemId, mapping]) => (
            <Badge key={itemId} tone="neutral" className="mr-1">
              {itemId}: {Object.keys(mapping).join(',')}
            </Badge>
          ))}
          {nonConsecutive.length > 6 && <span> and {nonConsecutive.length - 6} more.</span>}
        </Callout>
      )}
    </div>
  )
}
