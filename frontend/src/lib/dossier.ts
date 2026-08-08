/**
 * Comparison-dossier presentation logic.
 *
 * `ComparisonDossier` has no `best_model` field, deliberately (see the module
 * docstring in `backend/app/psychometrics/comparison.py`). This module is the
 * only place the frontend interprets it, and it is written so that the *type*
 * of its output makes a winner unrepresentable: there is no `winner`, `best` or
 * `recommended` key anywhere in `PresentedDossier`, and every row carries the
 * same neutral `RowRole` vocabulary.
 *
 * `leader` is a rank position on one criterion, not a verdict. It is surfaced
 * as `role: 'leads-on-held-out'` and always accompanied by
 * `leaderCaveat` — the sentence that says what leading does and does not mean.
 *
 * The `verdict` and `notes` strings from the backend are passed through
 * verbatim. They are written for display; paraphrasing them here would put a
 * second, unreviewed voice on top of a carefully hedged one.
 */

import type {
  ComparisonDossier,
  Disagreement,
  LikelihoodRatioTest,
  ModelEvidence,
} from '@/api/types'
import { CRITERION_AIC, CRITERION_BIC, CRITERION_CV, modelLabel } from '@/api/types'

/**
 * What a row is, in ranking terms only.
 *
 * There is no `'best'`. `'leads-on-held-out'` names a position on one criterion
 * and nothing else; `'tied-with-leader'` is used whenever the dossier reports
 * the leading models as statistically indistinguishable, so in that case no row
 * is singled out at all.
 */
export type RowRole =
  | 'leads-on-held-out'
  | 'tied-with-leader'
  | 'ranked'
  | 'not-ranked'

export interface PresentedModelRow {
  model: string
  label: string
  role: RowRole
  /** 1-based position on held-out predictive log-likelihood; null when unranked. */
  rank: number | null
  evidence: ModelEvidence
  /**
   * Held-out difference from the leader, in log-likelihood units. Negative or
   * zero. Null when either side has no held-out likelihood.
   */
  deltaFromLeader: number | null
  /**
   * Why this model takes no part in the ranking. Straight from
   * `ModelEvidence.failure_reason`; null when it is ranked.
   */
  excludedReason: string | null
}

export interface PresentedCriterion {
  name: string
  /** The model this criterion puts first, or null if it could score nothing. */
  first: string | null
  firstLabel: string | null
  order: string[]
  orderLabels: string[]
}

export interface PresentedDossier {
  /** Verbatim `dossier.verdict`. Never rewritten. */
  verdict: string
  /** Verbatim `dossier.notes`. */
  notes: string[]

  rows: PresentedModelRow[]
  criteria: PresentedCriterion[]
  disagreements: Disagreement[]
  likelihoodRatioTests: LikelihoodRatioTest[]

  indistinguishable: boolean
  criteriaAgree: boolean

  /** The model leading on held-out log-likelihood, or null. A position, not a pick. */
  leader: string | null
  leaderLabel: string | null
  /**
   * The sentence that must accompany any prominent display of `leader`.
   * Never null when `leader` is set.
   */
  leaderCaveat: string | null

  nFolds: number
  seed: number
  nRanked: number
  nExcluded: number
}

const INDISTINGUISHABLE_CAVEAT =
  'The leading models are statistically indistinguishable on held-out predictive ' +
  'log-likelihood. This ordering does not identify a better model, and a rerun ' +
  'with a different seed could reorder it. Choose on grounds outside this ' +
  'comparison — interpretability, an existing scale, or programme policy.'

const LEADER_CAVEAT =
  'Leading on held-out predictive log-likelihood is one line of evidence, not a ' +
  'recommendation. This report does not name a best model: read the secondary ' +
  'criteria, the disagreements between them, and the fit diagnostics before ' +
  'settling on a parameterisation.'

const SINGLE_CANDIDATE_CAVEAT =
  'Only one model could be evaluated on held-out data, so there is nothing to ' +
  'compare it against. A single model’s fit says how well it describes the ' +
  'data, not whether another model would describe it better.'

/** Criteria in reading order. Held-out first, because it is the primary one. */
const CRITERION_ORDER = [CRITERION_CV, CRITERION_AIC, CRITERION_BIC]

export function presentDossier(dossier: ComparisonDossier): PresentedDossier {
  const ranked = dossier.ranked ?? []

  // `ModelEvidence.usable` is a Python @property and so is absent from the
  // payload. It is `converged and cv_log_likelihood is not None` — recomputed
  // here against the same definition.
  const isUsable = (e: ModelEvidence) =>
    e.converged && e.cv_log_likelihood != null && Number.isFinite(e.cv_log_likelihood)

  const usable = ranked.filter(isUsable)
  const leaderEvidence = usable.length > 0 ? usable[0] : undefined
  const leaderValue = leaderEvidence?.cv_log_likelihood ?? null

  // When the dossier says the leaders are indistinguishable, *no* row gets the
  // leading role. The whole point of that flag is that the top of the ordering
  // is not meaningful, so highlighting a row would contradict it.
  const singleUsable = usable.length === 1
  const highlightLeader = !dossier.indistinguishable && !singleUsable

  let position = 0
  const rows: PresentedModelRow[] = ranked.map((evidence) => {
    const usableRow = isUsable(evidence)
    if (usableRow) position += 1

    let role: RowRole
    if (!usableRow) {
      role = 'not-ranked'
    } else if (dossier.indistinguishable) {
      role = 'tied-with-leader'
    } else if (position === 1 && highlightLeader) {
      role = 'leads-on-held-out'
    } else {
      role = 'ranked'
    }

    const value = evidence.cv_log_likelihood
    const delta =
      usableRow && leaderValue != null && value != null ? value - leaderValue : null

    return {
      model: evidence.model,
      label: modelLabel(evidence.model),
      role,
      rank: usableRow ? position : null,
      evidence,
      deltaFromLeader: delta,
      excludedReason: usableRow
        ? null
        : (evidence.failure_reason ??
          'This model produced no held-out predictive log-likelihood and the ' +
            'payload gives no reason.'),
    }
  })

  const criteria: PresentedCriterion[] = CRITERION_ORDER.filter(
    (name) => dossier.rankings?.[name] != null,
  ).map((name) => {
    const order = dossier.rankings[name] ?? []
    const first = dossier.first_choice?.[name] ?? null
    return {
      name,
      first,
      firstLabel: first == null ? null : modelLabel(first),
      order,
      orderLabels: order.map(modelLabel),
    }
  })

  let leaderCaveat: string | null = null
  if (dossier.leader != null) {
    if (dossier.indistinguishable) leaderCaveat = INDISTINGUISHABLE_CAVEAT
    else if (singleUsable) leaderCaveat = SINGLE_CANDIDATE_CAVEAT
    else leaderCaveat = LEADER_CAVEAT
  }

  return {
    verdict: dossier.verdict,
    notes: dossier.notes ?? [],
    rows,
    criteria,
    disagreements: dossier.disagreements ?? [],
    likelihoodRatioTests: dossier.likelihood_ratio_tests ?? [],
    indistinguishable: dossier.indistinguishable,
    // `criteria_agree` is a Python @property: `not self.disagreements`.
    criteriaAgree: (dossier.disagreements ?? []).length === 0,
    leader: dossier.leader,
    leaderLabel: dossier.leader == null ? null : modelLabel(dossier.leader),
    leaderCaveat,
    nFolds: dossier.n_folds,
    seed: dossier.seed,
    nRanked: usable.length,
    nExcluded: ranked.length - usable.length,
  }
}

/** Human sentence for one criterion disagreement. Framed as information. */
export function describeDisagreement(d: Disagreement): string {
  return (
    `${d.criterion_a} puts ${modelLabel(d.first_a)} first; ` +
    `${d.criterion_b} puts ${modelLabel(d.first_b)} first. ` +
    'The disagreement is reported rather than resolved.'
  )
}

/** Title for one likelihood-ratio row, e.g. "1PL restricted within 2PL". */
export function describeLikelihoodRatioTest(t: LikelihoodRatioTest): string {
  return `${modelLabel(t.restricted)} restricted within ${modelLabel(t.full)}`
}
