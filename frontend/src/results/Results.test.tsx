/**
 * Render smoke tests for the results screen.
 *
 * There is no database or queue on a dev machine, so the API cannot be
 * exercised live. These render the screen against hand-built payloads shaped
 * exactly as `analysis/serialise.to_jsonable` emits them, which is the only
 * check available that the report survives the two cases that matter: a
 * complete run, and a run where nearly every statistic is null.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import type { AnalysisResult, Diagnostics } from '@/api/types'
import { CRITERION_BIC, CRITERION_CV } from '@/api/types'
import { Results } from './Results'

function wrap(result: AnalysisResult) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, enabled: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <Results result={result} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const run: AnalysisResult['run'] = {
  id: 'run-1',
  dataset_id: 'ds-1',
  status: 'succeeded',
  requested_models: ['rasch', '2pl'],
  score_method: 'eap',
  seed: 20260803,
  engine_version: '2.0.0',
  created_at: '2026-08-06T09:00:00Z',
  started_at: '2026-08-06T09:00:01Z',
  finished_at: '2026-08-06T09:04:00Z',
  failure_reason: null,
  notes: ['Models are compared on k-fold held-out predictive log-likelihood.'],
}

const emptyAssumptions: Diagnostics['assumptions'] = {
  unidimensionality: null,
  local_independence: null,
}

/** A run where almost nothing could be computed. */
const sparse: Diagnostics = {
  sample: {
    n_persons: 300,
    n_items: 12,
    n_categories: [2, 2, 2],
    missing_rate: null,
    is_polytomous: false,
  },
  validation: { recoding: {}, dropped_items: [], n_persons_dropped: 0 },
  reference_model: null,
  reference_model_rationale: 'No model converged, so no item-level diagnostics could be computed.',
  score_method: 'eap',
  comparison: null,
  consequence: null,
  assumptions: emptyAssumptions,
  per_model: {},
  person_scores: null,
  dif: null,
  failures: [
    { diagnostic: 'unidimensionality', error: 'MemoryError: bootstrap exhausted memory' },
    { diagnostic: 'fit:2pl', error: 'LinAlgError: singular information matrix' },
  ],
  n_diagnostics_failed: 2,
  seed: 20260803,
  elapsed_seconds: 41.2,
}

/** A run that produced a comparison in which the models cannot be separated. */
const tied: Diagnostics = {
  ...sparse,
  reference_model: '2pl',
  reference_model_rationale:
    '2PL leads on held-out predictive log-likelihood, but the leading models are statistically indistinguishable on that criterion.',
  failures: [],
  n_diagnostics_failed: 0,
  comparison: {
    ranked: [
      {
        model: '2pl',
        converged: true,
        cv_log_likelihood: -2000,
        cv_per_respondent: -6.67,
        cv_standard_error: 30,
        folds: [],
        log_likelihood: -1950,
        n_free_parameters: 24,
        aic: 3948,
        bic: 4037,
        failure_reason: null,
        usable: true,
        notes: [],
      },
      {
        model: 'rasch',
        converged: true,
        cv_log_likelihood: -2010,
        cv_per_respondent: -6.7,
        cv_standard_error: 31,
        folds: [],
        log_likelihood: -1990,
        n_free_parameters: 13,
        aic: 4006,
        bic: 4054,
        failure_reason: null,
        usable: true,
        notes: [],
      },
    ],
    rankings: { [CRITERION_CV]: ['2pl', 'rasch'], [CRITERION_BIC]: ['2pl', 'rasch'] },
    first_choice: { [CRITERION_CV]: '2pl', [CRITERION_BIC]: '2pl' },
    disagreements: [],
    likelihood_ratio_tests: [
      {
        restricted: 'rasch',
        full: '2pl',
        performed: true,
        statistic: 80,
        df: 11,
        p_value: 0.0000001,
        refusal_reason: null,
      },
    ],
    criteria_agree: true,
    indistinguishable: true,
    leader: '2pl',
    verdict:
      'Models indistinguishable: 2PL and Rasch differ by 10.0 in held-out log-likelihood, within the 30.0 standard error of the paired per-fold differences across 5 folds. This comparison does not identify a better model.',
    n_folds: 5,
    seed: 20260803,
    notes: [],
  },
  per_model: {
    '2pl': {
      item_fit: {
        items: [
          {
            item_id: 'Q1',
            // infit 1.42 is outside 0.7-1.3, so the backend flags it.
            flagged: true,
            s_x2: null,
            s_x2_df: null,
            s_x2_p: null,
            s_x2_z: null,
            infit: 1.42,
            outfit: null,
            rmsd: 0.04,
            n_used: 300,
            notes: [],
          },
        ],
        n_persons_complete: 290,
        notes: [],
      },
      global_fit: null,
      reliability: null,
    },
  },
}


/** A run whose models disagree about individual respondents. */
const consequential: Diagnostics = {
  ...tied,
  consequence: {
    models: ['rasch', '2pl'],
    n_respondents_compared: 300,
    score_method: 'eap',
    selection_rates: [0.1, 0.25],
    pairs: [
      {
        model_a: 'rasch',
        model_b: '2pl',
        n_compared: 300,
        pearson_r: 0.9812,
        spearman_rho: 0.9744,
        mean_absolute_difference: 0.121,
        rms_difference: 0.164,
        p95_absolute_difference: 0.352,
        max_absolute_difference: 0.61,
        se_ratio_median: 1.04,
        reclassification: [
          {
            selection_rate: 0.1,
            n_selected_a: 36,
            n_selected_b: 30,
            n_reclassified: 8,
            proportion_reclassified: 0.0267,
            kappa: 0.861,
          },
          {
            selection_rate: 0.25,
            n_selected_a: 75,
            n_selected_b: 75,
            n_reclassified: 21,
            proportion_reclassified: 0.07,
            kappa: 0.813,
          },
        ],
        max_proportion_reclassified: 0.07,
      },
    ],
    stable: false,
    verdict:
      'At worst 7.0% of respondents changed side of a selection cut (rasch vs 2pl). That exceeds at least one of the thresholds this report uses.',
    notes: ['Differences are in standard deviations of this sample.'],
  },
}

describe('<Results>', () => {
  it('renders a run where almost every diagnostic failed, and says so up front', () => {
    wrap({ run, fits: [], diagnostics: sparse })

    expect(screen.getByText(/2 diagnostics could not be computed/i)).toBeTruthy()
    expect(screen.getByText(/MemoryError: bootstrap exhausted memory/)).toBeTruthy()
    // Absences are stated, not blank.
    expect(screen.getByText(/No comparison was produced/i)).toBeTruthy()
    expect(screen.getByText(/Unidimensionality was not assessed/i)).toBeTruthy()
    expect(screen.getByText(/DIF was not screened for this run/i)).toBeTruthy()
    expect(screen.getByText(/No person scores were summarised/i)).toBeTruthy()
  })

  it('renders the missing-rate null as "not computed", not as a zero', () => {
    const { container } = wrap({ run, fits: [], diagnostics: sparse })
    const absents = container.querySelectorAll('[data-absent="true"]')
    expect(absents.length).toBeGreaterThan(0)
    expect(container.textContent).toContain('not computed')
  })

  it('shows the indistinguishability verdict verbatim and highlights no model', () => {
    const { container } = wrap({ run, fits: [], diagnostics: tied })

    expect(
      screen.getByText(/This comparison does not identify a better model\./),
    ).toBeTruthy()
    expect(screen.getByText(/These models are not distinguishable/i)).toBeTruthy()
    // The badge vocabulary contains no winner claim.
    expect(container.textContent).not.toMatch(/\bbest model\b(?!.*does not)/i)
  })

  it('frames item-fit flags as something to look at, never as a bad item', () => {
    const { container } = wrap({ run, fits: [], diagnostics: tied })
    expect(screen.getByText(/A flag is an invitation to look, not a judgement/i)).toBeTruthy()
    // "bad item" may appear only inside the disclaimer that denies it.
    expect(container.textContent).toContain('not that it is a bad item')
    expect(container.textContent?.replace(/not that it is a bad item/g, '')).not.toMatch(
      /\bbad item\b/i,
    )
    // The flagged row states which criterion fired.
    expect(screen.getByText(/infit 1\.42 is outside 0\.7–1\.3/)).toBeTruthy()
  })

  it('shows the reference-model rationale as prose', () => {
    wrap({ run, fits: [], diagnostics: tied })
    expect(screen.getByText(/statistically indistinguishable on that criterion/i)).toBeTruthy()
  })


  it('reports what the model choice costs, verbatim and with its numbers', () => {
    wrap({ run, fits: [], diagnostics: consequential })

    expect(screen.getByText(/changed side of a selection cut/)).toBeTruthy()
    expect(screen.getByText('decisions differ')).toBeTruthy()
    // The statistics reach the table, not just the prose.
    expect(screen.getByText('0.9812')).toBeTruthy()
    expect(screen.getByText('0.352')).toBeTruthy()
    // Both selection counts, because they differ and the difference is a tie
    // boundary rather than a disagreement about anyone.
    expect(screen.getByText('36')).toBeTruthy()
    expect(screen.getByText('30')).toBeTruthy()
  })

  it('does not let a missing consequence analysis read as stability', () => {
    wrap({ run, fits: [], diagnostics: tied })

    expect(screen.getByText(/No consequence analysis was produced/i)).toBeTruthy()
    expect(screen.getByText(/has not been checked here/i)).toBeTruthy()
    expect(screen.queryByText('decisions stable')).toBeNull()
  })

  it('refuses to invent a report when the payload has no diagnostics', () => {
    wrap({ run, fits: [], diagnostics: null })
    expect(screen.getByText(/succeeded but stored no diagnostics payload/i)).toBeTruthy()
  })
})
