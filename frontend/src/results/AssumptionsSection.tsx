import type {
  Assumptions,
  LocalIndependenceReport,
  UnidimensionalityReport,
} from '@/api/types'
import { modelLabel } from '@/api/types'
import { ScreePlot } from '@/components/charts'
import { NumCell, Stat, Value } from '@/components/Value'
import { Badge, Callout, Notes, Panel, Table, Th } from '@/components/ui'
import { present, presentCount } from '@/lib/absence'
import { THRESHOLD_NOTES } from '@/lib/derive'

export function AssumptionsSection({
  id,
  assumptions,
  referenceModel,
}: {
  id: string
  assumptions: Assumptions
  referenceModel: string | null
}) {
  return (
    <Panel
      id={id}
      title="Assumptions"
      eyebrow="Before the fit statistics mean anything"
      description={
        <>
          Every model in this report assumes one latent trait and responses that are
          independent given it. If those do not hold, the fit statistics above are
          answering a question about a model that was never applicable.
        </>
      }
    >
      <div className="space-y-6">
        <Unidimensionality report={assumptions.unidimensionality} />
        <LocalIndependence
          report={assumptions.local_independence ?? null}
          referenceModel={referenceModel}
        />
      </div>
    </Panel>
  )
}

function Unidimensionality({ report }: { report: UnidimensionalityReport | null }) {
  if (report == null) {
    return (
      <Callout tone="absent" title="Unidimensionality was not assessed">
        No polychoric matrix, no parallel analysis, no MAP test and no bifactor
        approximation are available for this run. Whether one trait is enough to
        describe this instrument is an open question here, not a settled one.
      </Callout>
    )
  }

  const verdict = report.essentially_unidimensional

  return (
    <div className="space-y-4">
      <p className="eyebrow">Dimensionality</p>

      {verdict === true && (
        <Callout tone="steady" title="The conventional thresholds for a single score are met">
          Parallel analysis retains one factor, ECV is above 0.85 and
          omega-hierarchical is above 0.80. {THRESHOLD_NOTES.unidimensionality}
        </Callout>
      )}
      {verdict === false && (
        <Callout tone="attention" title="The evidence points away from a single score">
          Parallel analysis retains more than one factor and ECV is below 0.70.{' '}
          {THRESHOLD_NOTES.unidimensionality}
        </Callout>
      )}
      {verdict === null && (
        <Callout tone="attention" title="The evidence is mixed">
          The three procedures do not agree, or a component of the verdict was not
          computed. That is a real outcome, not a failure to reach one — the
          components are below and the judgement is yours.{' '}
          {THRESHOLD_NOTES.unidimensionality}
        </Callout>
      )}

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
        <Stat
          label="Factors (parallel analysis)"
          presented={presentCount(report.n_factors_parallel)}
        />
        <Stat label="Factors (MAP)" presented={presentCount(report.n_factors_map)} />
        <Stat
          label="ECV"
          presented={present(report.explained_common_variance, { places: 3 })}
          hint="Explained common variance. From a principal-component approximation to a bifactor pattern, not a fitted bifactor model."
        />
        <Stat
          label="PUC"
          presented={present(report.percent_uncontaminated, { places: 3 })}
          hint="Percent uncontaminated correlations. Above ~0.80 a high ECV is partly a consequence of the item grouping."
        />
        <Stat
          label="Omega-hierarchical"
          presented={present(report.omega_hierarchical, { places: 3 })}
        />
      </div>

      <ScreePlot eigenvalues={report.parallel.eigenvalues} />

      <details className="rounded border border-rule bg-raised px-4 py-3">
        <summary className="cursor-pointer text-small font-semibold text-ink">
          Eigenvalues and MAP series
        </summary>
        <div className="mt-3 space-y-4">
          <Table
            head={
              <tr>
                <Th>Component</Th>
                <Th>Observed</Th>
                <Th>Random mean</Th>
                <Th>Random 95th</Th>
                <Th align="left">Retained</Th>
              </tr>
            }
          >
            {report.parallel.eigenvalues.map((row) => (
              <tr key={row.component}>
                <NumCell presented={presentCount(row.component)} />
                <NumCell presented={present(row.observed, { places: 3 })} />
                <NumCell presented={present(row.random_mean, { places: 3 })} />
                <NumCell presented={present(row.random_p95, { places: 3 })} />
                <td className="px-3 py-2 text-left">
                  {row.retained ? (
                    <Badge tone="accent">retained</Badge>
                  ) : (
                    <span className="text-small text-ink-faint">not retained</span>
                  )}
                </td>
              </tr>
            ))}
          </Table>

          <div className="space-y-1">
            <p className="eyebrow">Velicer MAP</p>
            <p className="max-w-prose text-small text-ink-muted">
              Average squared and fourth-power partial correlations after m components
              are partialled out. The minimum is the point at which only common
              variance has been removed. The two variants disagreeing is informative
              in itself, which is why both are shown.
            </p>
            <Table
              head={
                <tr>
                  <Th>Components removed</Th>
                  <Th>Average squared</Th>
                  <Th>Average fourth power</Th>
                </tr>
              }
            >
              {report.map_test.average_squared.map((value, index) => (
                <tr key={index}>
                  <NumCell presented={presentCount(index)} />
                  <NumCell presented={present(value, { places: 4 })} />
                  <NumCell
                    presented={present(report.map_test.average_fourth[index], { places: 4 })}
                  />
                </tr>
              ))}
            </Table>
            <p className="text-small text-ink-muted">
              Minimum at{' '}
              <Value presented={presentCount(report.map_test.n_components_squared)} /> components
              (squared) and{' '}
              <Value presented={presentCount(report.map_test.n_components_fourth)} /> (fourth
              power).
            </p>
          </div>
        </div>
      </details>

      <Notes notes={report.notes} title="Dimensionality notes" />
      <Notes notes={report.bifactor.notes} title="Bifactor approximation caveats" />
      <Notes notes={report.parallel.notes} title="Parallel analysis notes" />
      <Notes notes={report.polychoric.notes} title="Polychoric matrix notes" />
    </div>
  )
}

function LocalIndependence({
  report,
  referenceModel,
}: {
  report: LocalIndependenceReport | null
  referenceModel: string | null
}) {
  if (report == null) {
    return (
      <Callout tone="absent" title="Local independence was not assessed">
        {referenceModel == null
          ? 'No model converged, so there was no parameterisation to compute residuals against.'
          : 'Q3 and the LD X² statistics did not complete for this run. No item pair has been screened for shared variance the trait does not explain.'}
      </Callout>
    )
  }

  const flagged = report.pairs.filter((p) => p.flagged)
  const shown = flagged.length > 0 ? flagged : [...report.pairs]
    .sort((a, b) => Math.abs(b.q3_star ?? 0) - Math.abs(a.q3_star ?? 0))
    .slice(0, 10)

  return (
    <div className="space-y-3">
      <p className="eyebrow">
        Local independence — {flagged.length} of {report.pairs.length} pairs flagged
      </p>

      <Callout tone="attention" title="A flagged pair is a pair to read together">
        {THRESHOLD_NOTES.localIndependence} Residuals were computed against{' '}
        {referenceModel == null ? 'the reference model' : modelLabel(referenceModel)}.
        Q3 carries a structural negative bias of roughly −1/(J−1) because θ is
        estimated from the same responses, so Q3* is the bias-corrected figure and is
        the one compared against the bootstrap critical value.
      </Callout>

      <div className="grid gap-4 sm:grid-cols-3">
        <Stat label="Mean Q3" presented={present(report.q3_mean, { places: 4 })} />
        <Stat
          label="Bootstrap critical value"
          presented={present(report.critical_value, {
            places: 4,
            reason:
              'The bootstrap null did not produce a critical value, so no pair could be tested against one.',
          })}
          hint={`α = ${report.alpha}, ${report.n_bootstrap} bootstrap draws, seed ${report.seed}`}
        />
        <Stat label="Pairs examined" presented={presentCount(report.pairs.length)} />
      </div>

      {report.pairs.length === 0 ? (
        <Callout tone="absent" title="No item pairs were examined" />
      ) : (
        <Table
          caption={
            flagged.length > 0
              ? 'Flagged pairs.'
              : 'No pair was flagged. The ten largest |Q3*| values are shown so the absence of flags is legible rather than inferred from an empty table.'
          }
          head={
            <tr>
              <Th align="left">Pair</Th>
              <Th>Q3</Th>
              <Th>Q3*</Th>
              <Th>LD X²</Th>
              <Th>df</Th>
              <Th>Signed z</Th>
              <Th align="left">Flag</Th>
            </tr>
          }
        >
          {shown.map((pair) => (
            <tr
              key={`${pair.index_a}-${pair.index_b}`}
              className={pair.flagged ? 'bg-attention-soft/40' : undefined}
            >
              <td className="numeric px-3 py-2 text-left">
                {pair.item_a} · {pair.item_b}
              </td>
              <NumCell presented={present(pair.q3, { places: 4 })} />
              <NumCell presented={present(pair.q3_star, { places: 4 })} />
              <NumCell presented={present(pair.ld_x2, { places: 2 })} />
              <NumCell presented={presentCount(pair.ld_df)} />
              <NumCell presented={present(pair.ld_signed_z, { places: 2 })} />
              <td className="px-3 py-2 text-left">
                {pair.flagged ? (
                  <Badge tone="attention">look</Badge>
                ) : (
                  <span className="text-small text-ink-faint">—</span>
                )}
              </td>
            </tr>
          ))}
        </Table>
      )}

      <Notes notes={report.notes} title="Local independence notes" />
    </div>
  )
}
