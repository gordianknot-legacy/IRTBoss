/**
 * Consequence analysis: does the model choice change any decision?
 *
 * This sits directly after the comparison dossier because it answers the question
 * the dossier deliberately leaves open. The dossier says which model describes the
 * data better and refuses to crown one; this says whether that refusal costs
 * anything — if the candidates rank and select the same people, it does not.
 *
 * Two things this screen must not do. It must not present the stability verdict as
 * a statement about fit, so the backend's wording is shown verbatim and the panel
 * is labelled as being about decisions. And it must not let `stable === null` read
 * as reassurance: a run with one model produces no comparison, and "nothing to
 * compare" is a different claim from "the choice does not matter".
 */

import type { ConsequenceReport, PairwiseConsequence } from '@/api/types'
import { modelLabel } from '@/api/types'
import { NumCell } from '@/components/Value'
import { Badge, Callout, Notes, Panel, Table, Th } from '@/components/ui'
import { present, presentCount } from '@/lib/absence'

function pairName(pair: PairwiseConsequence): string {
  return `${modelLabel(pair.model_a)} vs ${modelLabel(pair.model_b)}`
}

function StabilityBadge({ stable }: { stable: boolean | null }) {
  if (stable === null) return <Badge tone="neutral">not established</Badge>
  return stable ? (
    <Badge tone="steady">decisions stable</Badge>
  ) : (
    <Badge tone="attention">decisions differ</Badge>
  )
}

export function ConsequenceSection({
  id,
  consequence,
}: {
  id: string
  consequence: ConsequenceReport | null
}) {
  if (consequence == null) {
    return (
      <Panel id={id} title="Does the model choice change anything?" eyebrow="Consequences">
        <Callout tone="absent" title="No consequence analysis was produced">
          It needs at least two models that converged and were scored. Nothing is
          being shown in its place: that the models would agree is a claim, and it
          has not been checked here.
        </Callout>
      </Panel>
    )
  }

  return (
    <Panel
      id={id}
      title="Does the model choice change anything?"
      eyebrow="Consequences"
      description={
        <>
          The comparison above declines to name a winner. This is the question that
          leaves open: whether the candidates would reach different conclusions
          about these respondents. Score differences are in{' '}
          <strong>standard deviations of this sample</strong> — each model’s scores
          are standardised first, because Rasch and PCM leave the latent variance
          free and an unstandardised difference would report that convention as a
          finding. Correlations and reclassification counts need no such adjustment.
        </>
      }
    >
      <div className="space-y-5">
        <Callout
          tone={consequence.stable === false ? 'attention' : 'neutral'}
          title={
            <span className="inline-flex items-center gap-2">
              Verdict <StabilityBadge stable={consequence.stable} />
            </span>
          }
        >
          {consequence.verdict}
        </Callout>

        {consequence.pairs.length > 0 && (
          <div className="space-y-2">
            <p className="eyebrow">Agreement between models</p>
            <Table
              head={
                <tr>
                  <Th align="left">Pair</Th>
                  <Th>r</Th>
                  <Th>ρ</Th>
                  <Th>mean |Δθ|</Th>
                  <Th>95th |Δθ|</Th>
                  <Th>max |Δθ|</Th>
                  <Th>median SE ratio</Th>
                </tr>
              }
            >
              {consequence.pairs.map((pair) => (
                <tr key={`${pair.model_a}-${pair.model_b}`}>
                  <td className="px-3 py-2 text-left">{pairName(pair)}</td>
                  <NumCell presented={present(pair.pearson_r, { places: 4 })} />
                  <NumCell presented={present(pair.spearman_rho, { places: 4 })} />
                  <NumCell presented={present(pair.mean_absolute_difference, { places: 3 })} />
                  <NumCell presented={present(pair.p95_absolute_difference, { places: 3 })} />
                  <NumCell presented={present(pair.max_absolute_difference, { places: 3 })} />
                  <NumCell presented={present(pair.se_ratio_median, { places: 3 })} />
                </tr>
              ))}
            </Table>
            <p className="max-w-prose text-small text-ink-muted">
              A median SE ratio above 1 means the second model reports less precision
              for the same respondents.
            </p>
          </div>
        )}

        {consequence.pairs.length > 0 && (
          <div className="space-y-2">
            <p className="eyebrow">Who changes side of a cut</p>
            <p className="max-w-prose text-small text-ink-muted">
              At each selection rate the top proportion of respondents is taken under
              each model and the two selections compared. The rates are illustrative
              decision points, not a policy. A tied group straddling the cut is taken
              whole rather than split, so the two counts can differ — where they do,
              part of the reclassification is that boundary rather than a
              disagreement about anyone.
            </p>
            <Table
              head={
                <tr>
                  <Th align="left">Pair</Th>
                  <Th>rate</Th>
                  <Th>selected (A)</Th>
                  <Th>selected (B)</Th>
                  <Th>reclassified</Th>
                  <Th>κ</Th>
                </tr>
              }
            >
              {consequence.pairs.flatMap((pair) =>
                pair.reclassification.map((entry) => (
                  <tr key={`${pair.model_a}-${pair.model_b}-${entry.selection_rate}`}>
                    <td className="px-3 py-2 text-left">{pairName(pair)}</td>
                    <NumCell
                      presented={present(entry.selection_rate, {
                        percent: true,
                        places: 0,
                      })}
                    />
                    <NumCell presented={presentCount(entry.n_selected_a)} />
                    <NumCell presented={presentCount(entry.n_selected_b)} />
                    <NumCell
                      presented={present(entry.proportion_reclassified, {
                        percent: true,
                        places: 1,
                      })}
                    />
                    <NumCell presented={present(entry.kappa, { places: 3 })} />
                  </tr>
                )),
              )}
            </Table>
          </div>
        )}

        <Notes notes={consequence.notes} />
      </div>
    </Panel>
  )
}
