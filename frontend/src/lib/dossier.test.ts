import { describe, expect, it } from 'vitest'

import type { ComparisonDossier, ModelEvidence } from '@/api/types'
import { CRITERION_AIC, CRITERION_BIC, CRITERION_CV } from '@/api/types'
import { describeDisagreement, presentDossier } from './dossier'

function evidence(overrides: Partial<ModelEvidence> & { model: string }): ModelEvidence {
  return {
    converged: true,
    cv_log_likelihood: null,
    cv_per_respondent: null,
    cv_standard_error: null,
    folds: [],
    log_likelihood: null,
    n_free_parameters: null,
    aic: null,
    bic: null,
    failure_reason: null,
  usable: true,
    notes: [],
    ...overrides,
  }
}

function dossier(overrides: Partial<ComparisonDossier> = {}): ComparisonDossier {
  return {
    ranked: [],
    rankings: {},
    first_choice: {},
    disagreements: [],
    likelihood_ratio_tests: [],
    indistinguishable: false,
  criteria_agree: true,
    leader: null,
    verdict: '',
    n_folds: 5,
    seed: 20260803,
    notes: [],
    ...overrides,
  }
}

/**
 * The load-bearing property: nothing this module produces can be read as "the
 * best model". Enforced structurally (no such key exists) and lexically (the
 * vocabulary it emits contains no winner words).
 */
const WINNER_WORDS = /\b(best|winner|wins|won|recommend(ed|s)?|optimal|superior|correct model|choose this)\b/i

/**
 * Prose is allowed to *deny* that a winner exists — "does not name a best
 * model" is the sentence we want, not one we want to ban. So negated clauses
 * are removed before the winner vocabulary is looked for; what remains is any
 * affirmative designation.
 */
const NEGATIONS =
  /\b(?:not|no|never|nothing|does not|do not|is not|are not|cannot|without)\b[^.;:]*/gi

function affirmativeWinnerClaim(text: string): boolean {
  return WINNER_WORDS.test(text.replace(NEGATIONS, ' '))
}

describe('presentDossier — never designates a winner', () => {
  const twoModels = dossier({
    ranked: [
      evidence({ model: '2pl', cv_log_likelihood: -4000, cv_standard_error: 12 }),
      evidence({ model: 'rasch', cv_log_likelihood: -4200, cv_standard_error: 14 }),
    ],
    rankings: { [CRITERION_CV]: ['2pl', 'rasch'], [CRITERION_AIC]: ['2pl', 'rasch'] },
    first_choice: { [CRITERION_CV]: '2pl', [CRITERION_AIC]: '2pl' },
    leader: '2pl',
    verdict: '2PL predicts held-out responses better than Rasch by 200.0 in log-likelihood.',
  })

  it('exposes no winner-shaped field', () => {
    const presented = presentDossier(twoModels)
    const keys = Object.keys(presented)
    expect(keys).not.toContain('best')
    expect(keys).not.toContain('bestModel')
    expect(keys).not.toContain('winner')
    expect(keys).not.toContain('recommended')
    expect(keys.some((k) => WINNER_WORDS.test(k))).toBe(false)
  })

  it('uses only rank-position vocabulary for roles', () => {
    const roles = presentDossier(twoModels).rows.map((r) => r.role)
    expect(roles).toEqual(['leads-on-held-out', 'ranked'])
    for (const role of roles) expect(role).not.toMatch(WINNER_WORDS)
  })

  it('makes no affirmative winner claim in the caveat it attaches to the leader', () => {
    const caveat = presentDossier(twoModels).leaderCaveat ?? ''
    // Winner vocabulary appears only inside a denial.
    expect(caveat).toContain('does not name a best model')
    expect(caveat).toContain('not a recommendation')
    expect(affirmativeWinnerClaim(caveat)).toBe(false)
  })

  it('makes no affirmative winner claim in any caveat it can emit', () => {
    const variants = [
      twoModels,
      dossier({ ...twoModels, indistinguishable: true }),
      dossier({
        ...twoModels,
        ranked: [twoModels.ranked[0]!],
        rankings: { [CRITERION_CV]: ['2pl'] },
      }),
    ]
    for (const variant of variants) {
      const caveat = presentDossier(variant).leaderCaveat ?? ''
      expect(caveat).not.toBe('')
      expect(affirmativeWinnerClaim(caveat)).toBe(false)
    }
  })

  it('always attaches a caveat whenever a leader is present', () => {
    for (const flag of [true, false]) {
      const presented = presentDossier(dossier({ ...twoModels, indistinguishable: flag }))
      expect(presented.leader).not.toBeNull()
      expect(presented.leaderCaveat).not.toBeNull()
    }
  })

  it('passes the backend verdict through verbatim', () => {
    expect(presentDossier(twoModels).verdict).toBe(twoModels.verdict)
  })

  it('passes backend notes through verbatim', () => {
    const withNotes = dossier({ ...twoModels, notes: ['a note', 'another note'] })
    expect(presentDossier(withNotes).notes).toEqual(['a note', 'another note'])
  })
})

describe('presentDossier — indistinguishable models', () => {
  const tied = dossier({
    ranked: [
      evidence({ model: 'grm', cv_log_likelihood: -900, cv_standard_error: 40 }),
      evidence({ model: 'gpcm', cv_log_likelihood: -905, cv_standard_error: 41 }),
    ],
    rankings: { [CRITERION_CV]: ['grm', 'gpcm'] },
    first_choice: { [CRITERION_CV]: 'grm' },
    indistinguishable: true,
    leader: 'grm',
    verdict: 'Models indistinguishable: Graded Response and Generalised Partial Credit differ by 5.0.',
  })

  it('singles out no row when the models are not separated', () => {
    const roles = presentDossier(tied).rows.map((r) => r.role)
    expect(roles).toEqual(['tied-with-leader', 'tied-with-leader'])
    expect(roles).not.toContain('leads-on-held-out')
  })

  it('replaces the leader caveat with the indistinguishability statement', () => {
    const caveat = presentDossier(tied).leaderCaveat ?? ''
    expect(caveat).toContain('statistically indistinguishable')
    expect(caveat).toContain('does not identify a better model')
  })

  it('still reports the leader field, because the payload does', () => {
    expect(presentDossier(tied).leader).toBe('grm')
  })
})

describe('presentDossier — a single evaluable candidate', () => {
  const single = dossier({
    ranked: [
      evidence({ model: '2pl', cv_log_likelihood: -100, cv_standard_error: 3 }),
      evidence({
        model: '3pl',
        converged: false,
        failure_reason: '3 of 5 training folds did not converge',
      }),
    ],
    rankings: { [CRITERION_CV]: ['2pl'] },
    first_choice: { [CRITERION_CV]: '2pl' },
    leader: '2pl',
    verdict: 'Only 2PL could be evaluated on held-out data.',
  })

  it('does not highlight the only candidate as leading', () => {
    const presented = presentDossier(single)
    expect(presented.rows[0]?.role).toBe('ranked')
    expect(presented.rows.map((r) => r.role)).not.toContain('leads-on-held-out')
  })

  it('says there is nothing to compare against', () => {
    expect(presentDossier(single).leaderCaveat ?? '').toContain('nothing to compare it against')
  })

  it('counts ranked and excluded models separately', () => {
    const presented = presentDossier(single)
    expect(presented.nRanked).toBe(1)
    expect(presented.nExcluded).toBe(1)
  })
})

describe('presentDossier — models that take no part in the ranking', () => {
  it('marks them not-ranked and carries their reason', () => {
    const presented = presentDossier(
      dossier({
        ranked: [
          evidence({ model: '2pl', cv_log_likelihood: -50, cv_standard_error: 2 }),
          evidence({ model: 'rasch', converged: false, failure_reason: 'did not converge' }),
        ],
      }),
    )
    const excluded = presented.rows[1]
    expect(excluded?.role).toBe('not-ranked')
    expect(excluded?.rank).toBeNull()
    expect(excluded?.excludedReason).toBe('did not converge')
    expect(excluded?.deltaFromLeader).toBeNull()
  })

  it('supplies a reason even when the payload gives none', () => {
    const presented = presentDossier(
      dossier({ ranked: [evidence({ model: 'rasch', converged: false })] }),
    )
    expect(presented.rows[0]?.excludedReason).toBeTruthy()
  })

  it('treats a converged model with no held-out likelihood as unranked', () => {
    // `ModelEvidence.usable` is `converged and cv_log_likelihood is not None`;
    // that property is not on the wire, so this checks the recomputation.
    const presented = presentDossier(
      dossier({
        ranked: [
          evidence({ model: '2pl', converged: true, cv_log_likelihood: null }),
        ],
      }),
    )
    expect(presented.rows[0]?.role).toBe('not-ranked')
    expect(presented.nRanked).toBe(0)
  })
})

describe('presentDossier — criteria and disagreements', () => {
  const disagreeing = dossier({
    ranked: [
      evidence({ model: '2pl', cv_log_likelihood: -10, cv_standard_error: 1, aic: 30, bic: 45 }),
      evidence({ model: 'rasch', cv_log_likelihood: -12, cv_standard_error: 1, aic: 32, bic: 40 }),
    ],
    rankings: {
      [CRITERION_CV]: ['2pl', 'rasch'],
      [CRITERION_AIC]: ['2pl', 'rasch'],
      [CRITERION_BIC]: ['rasch', '2pl'],
    },
    first_choice: {
      [CRITERION_CV]: '2pl',
      [CRITERION_AIC]: '2pl',
      [CRITERION_BIC]: 'rasch',
    },
    disagreements: [
      {
        criterion_a: CRITERION_CV,
        criterion_b: CRITERION_BIC,
        first_a: '2pl',
        first_b: 'rasch',
      },
    ],
    leader: '2pl',
    verdict: 'x',
  })

  it('reports held-out first and preserves every criterion', () => {
    const names = presentDossier(disagreeing).criteria.map((c) => c.name)
    expect(names).toEqual([CRITERION_CV, CRITERION_AIC, CRITERION_BIC])
  })

  it('labels model keys without losing the raw key for unknown ones', () => {
    const criterion = presentDossier(disagreeing).criteria[0]
    expect(criterion?.orderLabels).toEqual(['2PL', 'Rasch'])
  })

  it('reports criteriaAgree as false when disagreements exist', () => {
    expect(presentDossier(disagreeing).criteriaAgree).toBe(false)
    expect(presentDossier(dossier()).criteriaAgree).toBe(true)
  })

  it('describes a disagreement without resolving it', () => {
    const sentence = describeDisagreement(disagreeing.disagreements[0]!)
    expect(sentence).toContain('2PL')
    expect(sentence).toContain('Rasch')
    expect(sentence).toContain('reported rather than resolved')
    expect(sentence).not.toMatch(/\b(best|winner|so use)\b/i)
  })
})

describe('presentDossier — deltas from the top of the ordering', () => {
  it('is zero for the top row and negative below it', () => {
    const presented = presentDossier(
      dossier({
        ranked: [
          evidence({ model: '2pl', cv_log_likelihood: -100, cv_standard_error: 5 }),
          evidence({ model: 'rasch', cv_log_likelihood: -140, cv_standard_error: 6 }),
        ],
      }),
    )
    expect(presented.rows[0]?.deltaFromLeader).toBe(0)
    expect(presented.rows[1]?.deltaFromLeader).toBe(-40)
  })
})

describe('presentDossier — empty and degenerate dossiers', () => {
  it('survives a dossier with no models at all', () => {
    const presented = presentDossier(dossier({ verdict: 'No model produced a held-out likelihood.' }))
    expect(presented.rows).toEqual([])
    expect(presented.leader).toBeNull()
    expect(presented.leaderCaveat).toBeNull()
    expect(presented.nRanked).toBe(0)
  })
})
