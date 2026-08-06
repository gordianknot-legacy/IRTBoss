import type { PersonScoreSummary } from '@/api/types'
import { modelLabel } from '@/api/types'
import { PercentileStrip } from '@/components/charts'
import { NumCell, Stat } from '@/components/Value'
import { Callout, Panel, Table, Th } from '@/components/ui'
import { present, presentCount } from '@/lib/absence'

const METHOD_LABELS: Record<string, string> = {
  eap: 'Expected a posteriori (EAP)',
  map: 'Maximum a posteriori (MAP)',
  wle: 'Weighted likelihood (Warm)',
}

export function PersonScoresSection({
  id,
  scores,
  referenceModel,
}: {
  id: string
  scores: PersonScoreSummary | null
  referenceModel: string | null
}) {
  if (scores == null) {
    return (
      <Panel id={id} title="Person scores" eyebrow="Distribution">
        <Callout tone="absent" title="No person scores were summarised">
          Scores are summarised only for the reference model, and only when that
          model’s scoring step completed. Neither happened for this run, so there is
          no trait distribution to show.
        </Callout>
      </Panel>
    )
  }

  const percentiles = scores.percentiles ?? {}

  return (
    <Panel
      id={id}
      title="Person scores"
      eyebrow="Distribution"
      description={
        <>
          {METHOD_LABELS[scores.method] ?? scores.method} estimates under{' '}
          {referenceModel == null ? 'the reference model' : modelLabel(referenceModel)}.
          Only the shape of the distribution is stored on the report; the full θ vector
          is a per-respondent result and does not belong inlined in every payload.
        </>
      }
    >
      <div className="space-y-5">
        {scores.n_unscorable > 0 && (
          <Callout
            tone="attention"
            title={`${scores.n_unscorable.toLocaleString('en-GB')} respondents could not be scored`}
          >
            {scores.note ??
              'They answered no items. They are reported as absent rather than assigned ' +
                'the prior mean, which would place them at the centre of the ' +
                'distribution as though they had been measured there.'}
          </Callout>
        )}

        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Stat label="Scored" presented={presentCount(scores.n_scored)} />
          <Stat label="Unscorable" presented={presentCount(scores.n_unscorable)} />
          <Stat
            label="Mean θ"
            presented={present(scores.mean, {
              places: 3,
              reason: 'No respondent produced a finite score, so there is no mean.',
            })}
          />
          <Stat
            label="SD of θ"
            presented={present(scores.sd, {
              places: 3,
              reason:
                'A standard deviation needs at least two scored respondents; fewer were scored.',
            })}
          />
        </div>

        <PercentileStrip
          title="Trait distribution"
          caption="Scored respondents only."
          percentiles={percentiles}
          minimum={scores.minimum ?? null}
          maximum={scores.maximum ?? null}
          mean={scores.mean ?? null}
        />

        <Table
          head={
            <tr>
              <Th align="left">Quantile</Th>
              <Th>θ</Th>
            </tr>
          }
        >
          <tr>
            <td className="px-3 py-2 text-left">Minimum</td>
            <NumCell presented={present(scores.minimum, { places: 3 })} />
          </tr>
          {['5', '25', '50', '75', '95'].map((p) => (
            <tr key={p}>
              <td className="px-3 py-2 text-left">{p}th percentile</td>
              <NumCell presented={present(percentiles[p], { places: 3 })} />
            </tr>
          ))}
          <tr>
            <td className="px-3 py-2 text-left">Maximum</td>
            <NumCell presented={present(scores.maximum, { places: 3 })} />
          </tr>
        </Table>
      </div>
    </Panel>
  )
}
