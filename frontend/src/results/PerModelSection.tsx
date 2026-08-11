import { useState } from 'react'

import type {
  GlobalFitResult,
  ItemFitReport,
  ModelFit,
  PerModelDiagnostics,
  ReliabilityReport,
} from '@/api/types'
import { modelLabel } from '@/api/types'
import { LineChart } from '@/components/charts'
import { NumCell, Stat, Value } from '@/components/Value'
import { Badge, Callout, Notes, Table, Th } from '@/components/ui'
import {
  present,
  presentCount,
  presentInterval,
  presentP,
  presentWithError,
} from '@/lib/absence'
import { THRESHOLD_NOTES, itemFitReasons } from '@/lib/derive'

export function PerModelSection({
  modelKey,
  diagnostics,
  fit,
  isReference,
}: {
  modelKey: string
  diagnostics: PerModelDiagnostics | null
  fit: ModelFit | null
  isReference: boolean
}) {
  if (modelKey === '' || diagnostics == null) {
    return (
      <Callout tone="absent" title="No per-model diagnostics">
        No model in this run produced item fit, global fit or reliability. Only models
        that converged are diagnosed, and an unconverged fit has no estimates to
        report — only a failure to.
      </Callout>
    )
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="font-display text-title text-ink">{modelLabel(modelKey)}</h3>
        {isReference && <Badge tone="accent">reference model</Badge>}
        {fit != null && !fit.converged && <Badge tone="alarm">did not converge</Badge>}
      </div>

      {fit != null && <FitSummary fit={fit} />}
      <GlobalFitBlock result={diagnostics.global_fit} />
      <ReliabilityBlock report={diagnostics.reliability} />
      <ItemFitBlock report={diagnostics.item_fit} isReference={isReference} />
      {fit != null && <ItemParameters fit={fit} />}
    </div>
  )
}

function FitSummary({ fit }: { fit: ModelFit }) {
  return (
    <div className="space-y-3">
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
        <Stat
          label="Log-likelihood"
          presented={present(fit.log_likelihood, { places: 1, reason: fit.failure_reason })}
        />
        <Stat label="Free parameters" presented={presentCount(fit.n_free_parameters)} />
        <Stat label="AIC" presented={present(fit.aic, { places: 1 })} />
        <Stat label="BIC" presented={present(fit.bic, { places: 1 })} />
        <Stat
          label="Latent SD"
          presented={present(fit.latent_sd, { places: 3 })}
          hint="Rasch and PCM leave the latent variance free; every downstream statistic is integrated on this metric."
        />
      </div>
      {fit.failure_reason != null && (
        <Callout tone="alarm" title="This fit reported a failure">
          {fit.failure_reason}
        </Callout>
      )}
      <Notes notes={fit.notes} title="Estimation notes" />
    </div>
  )
}

function GlobalFitBlock({ result }: { result: GlobalFitResult | null }) {
  if (result == null) {
    return (
      <Callout tone="absent" title="Global fit was not computed for this model">
        The limited-information global fit test did not produce a result. Its failure,
        if one was recorded, is listed under diagnostic coverage at the top of this
        report.
      </Callout>
    )
  }

  const reason = result.failure_reason

  return (
    <div className="space-y-3">
      <p className="eyebrow">Global fit — {result.statistic_name}</p>
      {reason != null && (
        <Callout tone="absent" title={`${result.statistic_name} could not be formed`}>
          {reason}
        </Callout>
      )}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stat
          label={result.statistic_name}
          presented={present(result.statistic, { places: 2, reason })}
        />
        <Stat
          label="df"
          presented={presentCount(result.df, { reason })}
          hint={`${result.n_moments} moments, ${result.n_free_parameters} free parameters`}
        />
        <Stat label="p" presented={presentP(result.p_value, { reason })} />
        <Stat
          label="Respondents used"
          presented={presentCount(result.n_persons_used)}
          hint="Complete cases only."
        />
        <Stat
          label="RMSEA₂"
          presented={present(result.rmsea2, { places: 4, reason })}
          hint="Root mean square error of approximation on the limited-information statistic."
        />
        <Stat
          label={`RMSEA₂ ${result.rmsea2_confidence * 100}% interval`}
          presented={presentInterval(result.rmsea2_lower, result.rmsea2_upper, {
            places: 4,
            reason,
          })}
        />
        <Stat
          label="SRMSR"
          presented={present(result.srmsr, { places: 4, reason })}
          hint="Standardised root mean square residual of the bivariate margins."
        />
      </div>
      <Notes notes={result.notes} title="Global fit notes" />
    </div>
  )
}

function ReliabilityBlock({ report }: { report: ReliabilityReport | null }) {
  if (report == null) {
    return (
      <Callout tone="absent" title="Reliability was not computed for this model">
        No marginal reliability, no omega and no conditional standard error curve are
        available. There is nothing to read in place of them.
      </Callout>
    )
  }

  const grid = report.theta_grid

  return (
    <div className="space-y-4">
      <p className="eyebrow">Reliability and measurement precision</p>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stat
          label="Marginal reliability (Bayesian)"
          presented={present(report.marginal_bayesian, { places: 3 })}
          hint="Model-implied, integrating the posterior variance over the trait distribution."
        />
        <Stat
          label="Marginal reliability (information)"
          presented={present(report.marginal_information, { places: 3 })}
          hint="Uses the ML error variance; can go negative where the test carries almost no information."
        />
        <Stat
          label="Empirical reliability"
          presented={present(report.empirical, { places: 3 })}
          hint="From the realised scores — the only figure here computed from respondents rather than from the model, and so the only one that can disagree with it."
        />
        <Stat label="Omega" presented={present(report.omega, { places: 3 })} />
      </div>

      <LineChart
        title="Conditional standard error of measurement"
        caption="How precisely each point on the trait scale is measured. A test can be reliable on average and still measure badly at the ends, which a single reliability figure cannot show."
        x={grid.map((v) => v ?? Number.NaN)}
        xLabel="θ (logits)"
        yLabel="SEM"
        series={[
          { label: 'Bayesian (EAP)', y: report.conditional_sem_bayesian },
          { label: 'Maximum likelihood', y: report.conditional_sem_ml, dashed: true },
        ]}
        markers={[
          { value: 0.5, label: 'SEM 0.50' },
          { value: 0.33, label: 'SEM 0.33' },
        ]}
      />

      <LineChart
        title="Test information"
        caption="Plotted separately from the standard error rather than on a second axis: the two are different scales and one figure with two y-axes invites a comparison neither supports."
        x={grid.map((v) => v ?? Number.NaN)}
        xLabel="θ (logits)"
        yLabel="information"
        series={[{ label: 'test information', y: report.test_information }]}
      />

      <div className="space-y-2">
        <p className="eyebrow">Precision bands</p>
        <p className="max-w-prose text-small text-ink-muted">
          The widest <em>contiguous</em> span of the scale meeting each standard-error
          bar. Contiguity matters: a test can meet a bar in two disconnected pockets,
          and reporting min-to-max across both would claim precision in the gap between
          them that the test does not have.
        </p>
        <Table
          head={
            <tr>
              <Th align="left">Max SEM</Th>
              <Th align="left">Span of θ</Th>
              <Th>Width</Th>
              <Th>Reliability equivalent</Th>
            </tr>
          }
        >
          {report.bands.map((band) => {
            const span = presentInterval(band.lower, band.upper, {
              places: 2,
              reason:
                'No part of the trait range is measured to this standard error, so there is no span.',
            })
            return (
              <tr key={band.max_sem}>
                <td className="numeric px-3 py-2 text-left">{band.max_sem.toFixed(2)}</td>
                <td className="px-3 py-2 text-left">
                  <Value presented={span} />
                </td>
                <NumCell
                  presented={present(span.kind === 'value' ? span.value : null, {
                    places: 2,
                  })}
                />
                <NumCell presented={present(band.reliability_equivalent, { places: 3 })} />
              </tr>
            )
          })}
        </Table>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <Stat
          label="Peak information at θ"
          presented={present(report.peak_information_at, { places: 2 })}
        />
        <Stat label="Latent SD used" presented={present(report.latent_sd, { places: 3 })} />
      </div>

      <Notes notes={report.notes} title="Reliability notes" />
    </div>
  )
}

type ItemSort = 'position' | 'flagged'

function ItemFitBlock({
  report,
  isReference,
}: {
  report: ItemFitReport | null
  isReference: boolean
}) {
  const [sort, setSort] = useState<ItemSort>('flagged')

  if (report == null) {
    return (
      <Callout tone="absent" title="Item fit was not computed for this model">
        No S-X², no mean-squares and no RMSD are available for any item. Nothing is
        shown in place of them.
      </Callout>
    )
  }

  const rows = report.items.map((item) => ({
    item,
    flagged: item.flagged,
    reasons: itemFitReasons(item),
  }))
  const flaggedCount = rows.filter((r) => r.flagged).length
  const ordered =
    sort === 'flagged'
      ? [...rows].sort((a, b) => Number(b.flagged) - Number(a.flagged))
      : rows

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="eyebrow">
          Item fit — {flaggedCount} of {rows.length} items worth a look
        </p>
        <button
          type="button"
          onClick={() => setSort((s) => (s === 'flagged' ? 'position' : 'flagged'))}
          className="text-small font-semibold text-accent hover:underline"
        >
          {sort === 'flagged' ? 'Show in item order' : 'Show flagged first'}
        </button>
      </div>

      <Callout tone="attention" title="A flag is an invitation to look, not a judgement">
        {THRESHOLD_NOTES.itemFit}
        {!isReference && (
          <p className="mt-2">
            These residuals were computed against this model, which is <em>not</em> the
            reference model for this run. The flags below will differ from those on the
            reference.
          </p>
        )}
      </Callout>

      <Table
        caption={`S-X² uses the ${report.n_persons_complete.toLocaleString('en-GB')} respondents with no missing responses; a rest score is undefined when part of the pattern is absent.`}
        head={
          <tr>
            <Th align="left">Item</Th>
            <Th align="left">Look at</Th>
            <Th>S-X²</Th>
            <Th>df</Th>
            <Th>p</Th>
            <Th>z</Th>
            <Th>Infit</Th>
            <Th>Outfit</Th>
            <Th>RMSD</Th>
            <Th>n used</Th>
          </tr>
        }
      >
        {ordered.map(({ item, flagged, reasons }) => (
          <tr key={item.item_id} className={flagged ? 'bg-attention-soft/40' : undefined}>
            <td className="numeric px-3 py-2 text-left">{item.item_id}</td>
            <td className="max-w-prose px-3 py-2 text-left">
              {flagged ? (
                <>
                  <Badge tone="attention">look</Badge>
                  <p className="mt-1 text-small text-ink-muted">{reasons.join('; ')}</p>
                </>
              ) : (
                <span className="text-small text-ink-faint">no criterion fired</span>
              )}
              {item.notes.length > 0 && (
                <p className="mt-1 text-small text-ink-muted">{item.notes.join(' ')}</p>
              )}
            </td>
            <NumCell presented={present(item.s_x2, { places: 2 })} />
            <NumCell presented={presentCount(item.s_x2_df)} />
            <NumCell presented={presentP(item.s_x2_p)} />
            <NumCell presented={present(item.s_x2_z, { places: 2 })} />
            <NumCell presented={present(item.infit, { places: 2 })} />
            <NumCell presented={present(item.outfit, { places: 2 })} />
            <NumCell presented={present(item.rmsd, { places: 3 })} />
            <NumCell presented={presentCount(item.n_used)} />
          </tr>
        ))}
      </Table>

      <Notes notes={report.notes} title="Item fit notes" />
    </div>
  )
}

function ItemParameters({ fit }: { fit: ModelFit }) {
  if (fit.item_parameters.length === 0) {
    return (
      <Callout tone="absent" title="No item parameters were stored for this model">
        An unconverged fit has no estimates to report.
      </Callout>
    )
  }
  const polytomous = fit.item_parameters.some((p) => p.thresholds.length > 0)

  return (
    <details className="rounded border border-rule bg-raised px-4 py-3">
      <summary className="cursor-pointer text-small font-semibold text-ink">
        Item parameters ({fit.item_parameters.length})
      </summary>
      <div className="mt-3 space-y-2">
        <p className="max-w-prose text-small text-ink-muted">
          Standard errors are shown beside each estimate. A missing standard error
          means it was not estimated — never that it is zero.
        </p>
        <Table
          head={
            <tr>
              <Th align="left">Item</Th>
              <Th>Categories</Th>
              <Th>Discrimination ± SE</Th>
              {polytomous ? <Th align="left">Thresholds</Th> : <Th>Difficulty ± SE</Th>}
              <Th>Guessing ± SE</Th>
            </tr>
          }
        >
          {fit.item_parameters.map((param) => (
            <tr key={param.item_id}>
              <td className="numeric px-3 py-2 text-left">{param.item_id}</td>
              <NumCell presented={presentCount(param.n_categories)} />
              <NumCell
                presented={presentWithError(param.discrimination, param.se_discrimination, {
                  places: 3,
                })}
              />
              {polytomous ? (
                <td className="numeric px-3 py-2 text-left">
                  {param.thresholds.length === 0 ? (
                    <Value presented={present(null)} />
                  ) : (
                    param.thresholds.map((t, i) => (
                      <span key={i} className="mr-2 inline-block">
                        <Value
                          presented={presentWithError(t, param.se_thresholds?.[i] ?? null, {
                            places: 2,
                          })}
                        />
                      </span>
                    ))
                  )}
                </td>
              ) : (
                <NumCell
                  presented={presentWithError(param.difficulty, param.se_difficulty, {
                    places: 3,
                  })}
                />
              )}
              <NumCell
                presented={presentWithError(param.guessing, param.se_guessing, {
                  places: 3,
                  reason:
                    param.guessing == null
                      ? 'This model has no lower asymptote; guessing is not a parameter of it.'
                      : null,
                })}
              />
            </tr>
          ))}
        </Table>
      </div>
    </details>
  )
}
