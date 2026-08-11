/**
 * The comparison dossier.
 *
 * Nothing on this screen says "best", "recommended", "winner" or "chosen". The
 * ordering is by held-out predictive log-likelihood and is labelled as such;
 * when `indistinguishable` is true, the top of that ordering is explicitly
 * withdrawn as meaningful and no row is highlighted at all.
 *
 * All the interpretive prose is the backend's: `verdict` and `notes` are shown
 * verbatim, and the refusal reasons on the likelihood-ratio tests are shown in
 * full rather than compressed to "n/a".
 */

import type { ComparisonDossier, ModelFit } from '@/api/types'
import { IntervalChart } from '@/components/charts'
import { NumCell, Value } from '@/components/Value'
import { Badge, Callout, Notes, Panel, Table, Th } from '@/components/ui'
import { present, presentCount, presentP } from '@/lib/absence'
import {
  describeDisagreement,
  describeLikelihoodRatioTest,
  presentDossier,
  type RowRole,
} from '@/lib/dossier'

const ROLE_LABEL: Record<RowRole, string | null> = {
  'leads-on-held-out': 'leads on held-out',
  'tied-with-leader': 'not separated',
  ranked: null,
  'not-ranked': 'not ranked',
}

export function ComparisonSection({
  id,
  dossier,
  fits,
}: {
  id: string
  dossier: ComparisonDossier | null
  fits: ModelFit[]
}) {
  if (dossier == null) {
    const converged = fits.filter((f) => f.converged)
    return (
      <Panel id={id} title="Model comparison" eyebrow="Evidence">
        <Callout tone="absent" title="No comparison was produced">
          {converged.length <= 1
            ? 'A comparison needs at least two models that converged. ' +
              `${converged.length} did, so there is nothing to compare. A single ` +
              'model’s fit statistics say how well it describes the data, not whether ' +
              'a different model would describe it better.'
            : 'Two or more models converged but the comparison did not complete. Its ' +
              'failure is listed under diagnostic coverage above; no ranking, no ' +
              'information criteria comparison and no likelihood-ratio ladder are ' +
              'available for this run.'}
        </Callout>
      </Panel>
    )
  }

  const presented = presentDossier(dossier)

  return (
    <Panel
      id={id}
      title="Model comparison"
      eyebrow="Evidence, not a recommendation"
      description={
        <>
          Models are ranked on <strong>k-fold held-out predictive log-likelihood</strong>,
          split by respondent, over {presented.nFolds} folds. That criterion works for
          non-nested comparisons and — unlike AIC or BIC — comes with a standard error,
          which is the only reason an “indistinguishable” verdict is possible at all.
          AIC, BIC and the likelihood-ratio ladder are reported alongside as secondary
          evidence. Where they disagree, the disagreement is shown rather than resolved.
        </>
      }
    >
      <div className="space-y-6">
        {/* The backend's own sentence, verbatim and prominent. */}
        <Callout
          tone={presented.indistinguishable ? 'attention' : 'accent'}
          title={presented.indistinguishable ? 'These models are not distinguishable' : 'Verdict'}
        >
          <p className="text-body">{presented.verdict}</p>
        </Callout>

        {presented.leaderCaveat != null && (
          <Callout tone="neutral" title="What the ordering does and does not mean">
            {presented.leaderCaveat}
          </Callout>
        )}

        <IntervalChart
          title="Held-out predictive log-likelihood"
          caption={`Total across ${presented.nFolds} folds, with ± one standard error of that total. Higher is better predicted; the bars are what decide whether the ordering means anything.`}
          valueLabel="held-out log-likelihood"
          rows={presented.rows.map((row) => ({
            label: row.label,
            value: row.evidence.cv_log_likelihood,
            error: row.evidence.cv_standard_error,
            muted: row.role === 'not-ranked',
          }))}
        />

        <div className="space-y-2">
          <p className="eyebrow">
            Ranked by held-out predictive log-likelihood ({presented.nRanked} ranked
            {presented.nExcluded > 0 && `, ${presented.nExcluded} not ranked`})
          </p>
          <Table
            head={
              <tr>
                <Th align="left">Model</Th>
                <Th title="Total held-out predictive log-likelihood across folds">
                  Held-out log-lik
                </Th>
                <Th title="Standard error of that total, across folds">± SE</Th>
                <Th title="Held-out log-likelihood per held-out respondent">Per respondent</Th>
                <Th title="Difference from the model at the top of this ordering">Δ from top</Th>
                <Th title="Log-likelihood of the fit to the full sample">Full-sample log-lik</Th>
                <Th>Free params</Th>
                <Th>AIC</Th>
                <Th>BIC</Th>
              </tr>
            }
          >
            {presented.rows.map((row) => (
              <tr
                key={row.model}
                className={row.role === 'not-ranked' ? 'text-ink-muted' : undefined}
              >
                <td className="px-3 py-2 text-left">
                  <span className="flex flex-wrap items-center gap-2">
                    <span className="font-semibold text-ink">{row.label}</span>
                    {row.rank != null && (
                      <span className="numeric text-ink-faint">#{row.rank}</span>
                    )}
                    {ROLE_LABEL[row.role] != null && (
                      <Badge
                        tone={
                          row.role === 'not-ranked'
                            ? 'absent'
                            : row.role === 'tied-with-leader'
                              ? 'attention'
                              : 'accent'
                        }
                      >
                        {ROLE_LABEL[row.role]}
                      </Badge>
                    )}
                  </span>
                  {row.excludedReason != null && (
                    <p className="mt-1 max-w-prose text-small text-ink-muted">
                      {row.excludedReason}
                    </p>
                  )}
                </td>
                <NumCell
                  presented={present(row.evidence.cv_log_likelihood, {
                    places: 1,
                    reason: row.excludedReason,
                  })}
                />
                <NumCell
                  presented={present(row.evidence.cv_standard_error, {
                    places: 1,
                    reason:
                      row.evidence.cv_standard_error == null && row.rank != null
                        ? 'The fold-to-fold variation could not be estimated, so this model’s position carries no uncertainty statement.'
                        : null,
                  })}
                />
                <NumCell presented={present(row.evidence.cv_per_respondent, { places: 3 })} />
                <NumCell
                  presented={present(row.deltaFromLeader, {
                    places: 1,
                    reason: 'No held-out likelihood, so no difference can be formed.',
                  })}
                />
                <NumCell presented={present(row.evidence.log_likelihood, { places: 1 })} />
                <NumCell presented={presentCount(row.evidence.n_free_parameters)} />
                <NumCell presented={present(row.evidence.aic, { places: 1 })} />
                <NumCell presented={present(row.evidence.bic, { places: 1 })} />
              </tr>
            ))}
          </Table>
        </div>

        {/* Criterion-by-criterion orderings. */}
        <div className="space-y-2">
          <p className="eyebrow">Each criterion’s ordering</p>
          {presented.criteria.length === 0 ? (
            <Callout tone="absent" title="No criterion could order these models">
              None of held-out log-likelihood, AIC or BIC produced a score for any
              model, so there is no ordering to show.
            </Callout>
          ) : (
            <ul className="space-y-2">
              {presented.criteria.map((criterion) => (
                <li
                  key={criterion.name}
                  className="flex flex-wrap items-baseline gap-x-3 gap-y-1 rounded border border-rule bg-raised px-3 py-2"
                >
                  <span className="text-small font-semibold text-ink">{criterion.name}</span>
                  <span className="text-small text-ink-muted">
                    {criterion.orderLabels.join(' › ')}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="space-y-2">
          <p className="eyebrow">Where the criteria disagree</p>
          {presented.criteriaAgree ? (
            <Callout tone="neutral">
              All {presented.criteria.length} criteria put the same model first. That is
              agreement between criteria, not evidence that the model is correct: BIC is
              directionally biased against the 3PL and every one of these criteria shares
              the same fitted likelihoods.
            </Callout>
          ) : (
            <ul className="space-y-2">
              {presented.disagreements.map((d, index) => (
                <li key={index}>
                  <Callout tone="attention">{describeDisagreement(d)}</Callout>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="space-y-2">
          <p className="eyebrow">
            Likelihood-ratio ladder ({presented.likelihoodRatioTests.length} pair
            {presented.likelihoodRatioTests.length === 1 ? '' : 's'})
          </p>
          <p className="max-w-prose text-small text-ink-muted">
            A refused test is a result, not an absence. The reason is shown in full:
            some of these pairs are not nested, and the 2PL-vs-3PL test is invalid
            because the null sits on the boundary of the parameter space.
          </p>
          {presented.likelihoodRatioTests.length === 0 ? (
            <Callout tone="absent" title="No pairs were tested">
              The dossier lists no likelihood-ratio tests for this set of models.
            </Callout>
          ) : (
            <Table
              head={
                <tr>
                  <Th align="left">Pair</Th>
                  <Th align="left">Status</Th>
                  <Th>χ²</Th>
                  <Th>df</Th>
                  <Th>p</Th>
                </tr>
              }
            >
              {presented.likelihoodRatioTests.map((test, index) => (
                <tr key={`${test.restricted}-${test.full}-${index}`}>
                  <td className="px-3 py-2 text-left">{describeLikelihoodRatioTest(test)}</td>
                  <td className="max-w-prose px-3 py-2 text-left">
                    {test.performed ? (
                      <Badge tone="steady">performed</Badge>
                    ) : (
                      <>
                        <Badge tone="absent">refused</Badge>
                        <p className="mt-1 text-small text-ink-muted">
                          {test.refusal_reason ??
                            'The dossier records no reason for the refusal.'}
                        </p>
                      </>
                    )}
                  </td>
                  <NumCell
                    presented={present(test.statistic, {
                      places: 2,
                      reason: test.performed ? null : 'The test was refused.',
                    })}
                  />
                  <NumCell
                    presented={presentCount(test.df, {
                      reason: test.performed ? null : 'The test was refused.',
                    })}
                  />
                  <NumCell
                    presented={presentP(test.p_value, {
                      reason: test.performed ? null : 'The test was refused.',
                    })}
                  />
                </tr>
              ))}
            </Table>
          )}
        </div>

        {/* Per-fold detail: what the standard errors are made of. */}
        <details className="rounded border border-rule bg-raised px-4 py-3">
          <summary className="cursor-pointer text-small font-semibold text-ink">
            Per-fold held-out log-likelihoods
          </summary>
          <div className="mt-3 space-y-4">
            {presented.rows.map((row) => (
              <div key={row.model} className="space-y-1">
                <p className="text-small font-semibold text-ink">{row.label}</p>
                {row.evidence.folds.length === 0 ? (
                  <p className="text-small text-absent">
                    No folds were evaluated for this model.
                  </p>
                ) : (
                  <Table
                    head={
                      <tr>
                        <Th>Fold</Th>
                        <Th>Train n</Th>
                        <Th>Test n</Th>
                        <Th>Held-out log-lik</Th>
                        <Th align="left">If it failed</Th>
                      </tr>
                    }
                  >
                    {row.evidence.folds.map((fold) => (
                      <tr key={fold.fold}>
                        <NumCell presented={presentCount(fold.fold + 1)} />
                        <NumCell presented={presentCount(fold.n_train)} />
                        <NumCell presented={presentCount(fold.n_test)} />
                        <NumCell
                          presented={present(fold.log_likelihood, {
                            places: 1,
                            reason: fold.failure_reason,
                          })}
                        />
                        <td className="max-w-prose px-3 py-2 text-left text-ink-muted">
                          {fold.failure_reason ?? ''}
                        </td>
                      </tr>
                    ))}
                  </Table>
                )}
              </div>
            ))}
          </div>
        </details>

        <Notes notes={presented.notes} title="Comparison notes" />

        <p className="max-w-prose text-small text-ink-faint">
          Folds are assigned with seed{' '}
          <Value presented={presentCount(presented.seed)} />. Re-running with a
          different seed reshuffles the folds and can reorder models whose held-out
          difference is small relative to its standard error.
          {presented.leader != null && (
            <>
              {' '}
              This report does not name a best model, and the payload it is built from
              has no field in which one could be recorded.
            </>
          )}
        </p>
      </div>
    </Panel>
  )
}
