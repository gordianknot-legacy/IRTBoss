/**
 * Wire types, transcribed from `backend/app/api/schemas.py`.
 *
 * Nothing here is inferred or widened. Where the backend declares `float | None`
 * this declares `number | null` — not `number | undefined` and not an optional
 * property — because the whole product turns on the difference between "no
 * value" and "zero", and an optional property lets a `?? 0` slip in unnoticed.
 */

export const MODEL_KEYS = ['rasch', '1pl', '2pl', '3pl', 'grm', 'pcm', 'gpcm'] as const
export type ModelKey = (typeof MODEL_KEYS)[number]

/** `ModelKey.label` from `backend/app/irt/families.py`. */
export const MODEL_LABELS: Record<ModelKey, string> = {
  rasch: 'Rasch',
  '1pl': '1PL',
  '2pl': '2PL',
  '3pl': '3PL',
  grm: 'Graded Response',
  pcm: 'Partial Credit',
  gpcm: 'Generalised Partial Credit',
}

export const POLYTOMOUS_MODELS: ReadonlySet<string> = new Set(['grm', 'pcm', 'gpcm'])

/** Falls back to the raw key: an unknown key must still be visible, not blank. */
export function modelLabel(key: string | null | undefined): string {
  if (key == null) return 'unknown model'
  return MODEL_LABELS[key as ModelKey] ?? key
}

export type StakesLevel = 'low' | 'medium' | 'high'
export type IntendedUse = 'research' | 'operational' | 'certification'
export type RunStatus = 'queued' | 'running' | 'succeeded' | 'failed'

export interface User {
  id: string
  email: string
  created_at: string
}

export interface Session {
  access_token: string
  token_type: string
  expires_in: number
  user: User
}

export interface Project {
  id: string
  name: string
  description: string | null
  stakes_level: StakesLevel
  intended_use: IntendedUse
  created_at: string
  updated_at: string
}

export interface ProjectCreate {
  name: string
  description?: string | null
  stakes_level: StakesLevel
  intended_use: IntendedUse
}

/** `column_metadata` is a bare `dict` on the wire; this is what `ingest._parse` puts in it. */
export interface ColumnMetadata {
  columns: string[]
  item_columns: string[]
  id_column: string | null
  group_columns: string[]
  observed_categories: Record<string, string[]>
}

export interface Dataset {
  id: string
  project_id: string
  original_filename: string
  checksum_sha256: string
  size_bytes: number
  n_persons: number
  n_items: number
  column_metadata: ColumnMetadata
  created_at: string
}

export interface ItemParameter {
  item_id: string
  position: number
  n_categories: number
  discrimination: number
  difficulty: number | null
  guessing: number | null
  thresholds: number[]
  se_discrimination: number | null
  se_difficulty: number | null
  se_guessing: number | null
  se_thresholds: number[] | null
}

export interface ModelFit {
  model_key: string
  converged: boolean
  log_likelihood: number | null
  n_free_parameters: number | null
  aic: number | null
  bic: number | null
  latent_sd: number | null
  elapsed_seconds: number | null
  failure_reason: string | null
  notes: string[]
  item_parameters: ItemParameter[]
}

export interface AnalysisRun {
  id: string
  dataset_id: string
  status: RunStatus
  requested_models: string[]
  seed: number
  engine_version: string
  created_at: string
  started_at: string | null
  finished_at: string | null
  failure_reason: string | null
  notes: string[]
}

export interface AnalysisResult {
  run: AnalysisRun
  fits: ModelFit[]
  diagnostics: Diagnostics | null
}

/* ------------------------------------------------------------------------ *
 * Diagnostics payload
 *
 * Assembled in `backend/app/analysis/orchestrator.run_analysis` and passed
 * through `analysis/serialise.to_jsonable`, which:
 *   - turns dataclasses into objects keyed by their *fields only*;
 *   - turns enums into their `.value` string;
 *   - turns numpy arrays into plain arrays;
 *   - turns every non-finite float into `null`.
 *
 * The "fields only" part used to matter a great deal: Python `@property`
 * accessors were dropped entirely, so `ItemFitResult.flagged`,
 * `ModelEvidence.usable`, `DIFResult.flagged_by` and
 * `UnidimensionalityReport.essentially_unidimensional` never reached the wire.
 * That was a backend defect and it is fixed — result classes opt properties in
 * by declaring `JSON_PROPERTIES`, and a test walks every class to check each
 * declared name is really a property. The flags below are therefore read from
 * the payload, never recomputed here: a threshold duplicated on this side is a
 * threshold that silently diverges the first time the backend tunes it.
 * ------------------------------------------------------------------------ */

export interface DiagnosticFailure {
  diagnostic: string
  error: string
}

export interface SampleSummary {
  n_persons: number
  n_items: number
  n_categories: number[]
  missing_rate: number | null
  is_polytomous: boolean
}

export interface DroppedItem {
  item_id: string
  reason: string
}

export interface ValidationSummary {
  recoding: Record<string, Record<string, number>>
  dropped_items: DroppedItem[]
  n_persons_dropped: number
}

/* --- comparison (psychometrics/comparison.py) --------------------------- */

export interface FoldResult {
  fold: number
  n_train: number
  n_test: number
  converged: boolean
  log_likelihood: number | null
  failure_reason: string | null
}

export interface ModelEvidence {
  model: string
  converged: boolean
  cv_log_likelihood: number | null
  cv_per_respondent: number | null
  cv_standard_error: number | null
  folds: FoldResult[]
  log_likelihood: number | null
  n_free_parameters: number | null
  aic: number | null
  bic: number | null
  /** From `ModelEvidence.usable`: converged AND scored on held-out data. */
  usable: boolean
  failure_reason: string | null
  notes: string[]
}

export interface LikelihoodRatioTest {
  restricted: string
  full: string
  performed: boolean
  statistic: number | null
  df: number | null
  p_value: number | null
  refusal_reason: string | null
}

export interface Disagreement {
  criterion_a: string
  criterion_b: string
  first_a: string
  first_b: string
}

export interface ComparisonDossier {
  ranked: ModelEvidence[]
  /** criterion name -> models best-first. Keys are the CV/AIC/BIC constants. */
  rankings: Record<string, string[]>
  first_choice: Record<string, string>
  disagreements: Disagreement[]
  likelihood_ratio_tests: LikelihoodRatioTest[]
  indistinguishable: boolean
  /** From `ComparisonDossier.criteria_agree`. */
  criteria_agree: boolean
  leader: string | null
  verdict: string
  n_folds: number
  seed: number
  notes: string[]
}

/** Criterion labels, verbatim from `comparison.CV` / `.AIC` / `.BIC`. */
export const CRITERION_CV = 'held-out log-likelihood'
export const CRITERION_AIC = 'AIC'
export const CRITERION_BIC = 'BIC'

/* --- item fit (psychometrics/itemfit.py) -------------------------------- */

export interface ItemFitResult {
  item_id: string
  /** From `ItemFitResult.flagged`. A screening prompt, not a verdict. */
  flagged: boolean
  s_x2: number | null
  s_x2_df: number | null
  s_x2_p: number | null
  s_x2_z: number | null
  infit: number | null
  outfit: number | null
  rmsd: number | null
  n_used: number
  notes: string[]
}

export interface ItemFitReport {
  items: ItemFitResult[]
  n_persons_complete: number
  notes: string[]
}

/* --- global fit (psychometrics/globalfit.py) ---------------------------- */

export interface GlobalFitResult {
  statistic_name: string
  statistic: number | null
  df: number | null
  p_value: number | null
  n_moments: number
  n_free_parameters: number
  n_persons_used: number
  rmsea2: number | null
  rmsea2_lower: number | null
  rmsea2_upper: number | null
  rmsea2_confidence: number
  srmsr: number | null
  failure_reason: string | null
  notes: string[]
}

/* --- reliability (psychometrics/reliability.py) ------------------------- */

export interface PrecisionBand {
  max_sem: number
  lower: number | null
  upper: number | null
  reliability_equivalent: number
}

export interface ReliabilityReport {
  marginal_bayesian: number | null
  marginal_information: number | null
  empirical: number | null
  omega: number | null
  latent_sd: number | null
  theta_grid: (number | null)[]
  test_information: (number | null)[]
  conditional_sem_bayesian: (number | null)[]
  conditional_sem_ml: (number | null)[]
  peak_information_at: number | null
  bands: PrecisionBand[]
  notes: string[]
}

/* --- assumptions (psychometrics/assumptions.py) ------------------------- */

export interface PolychoricMatrix {
  matrix: (number | null)[][]
  item_ids: string[]
  thresholds: (number | null)[][]
  min_pair_n: number
  notes: string[]
}

export interface EigenvalueRow {
  component: number
  observed: number | null
  random_mean: number | null
  random_p95: number | null
  retained: boolean
}

export interface ParallelAnalysisResult {
  n_factors_retained: number
  eigenvalues: EigenvalueRow[]
  n_iterations: number
  percentile: number
  seed: number
  notes: string[]
}

export interface MapResult {
  n_components_squared: number
  n_components_fourth: number
  average_squared: (number | null)[]
  average_fourth: (number | null)[]
  notes: string[]
}

export interface BifactorApproximation {
  general_loadings: (number | null)[]
  group_loadings: (number | null)[]
  group_assignment: number[]
  n_group_factors: number
  ecv: number | null
  puc: number | null
  omega_hierarchical: number | null
  omega_total: number | null
  notes: string[]
}

export interface UnidimensionalityReport {
  polychoric: PolychoricMatrix
  parallel: ParallelAnalysisResult
  map_test: MapResult
  bifactor: BifactorApproximation
  n_factors_parallel: number
  n_factors_map: number
  explained_common_variance: number | null
  percent_uncontaminated: number | null
  omega_hierarchical: number | null
  /**
   * From `UnidimensionalityReport.essentially_unidimensional`. `null` means the
   * evidence is mixed, which is a genuine outcome rather than a failure to
   * compute — render it as such, not as an absence.
   */
  essentially_unidimensional: boolean | null
  notes: string[]
}

export interface ItemPairStatistic {
  index_a: number
  index_b: number
  item_a: string
  item_b: string
  q3: number | null
  q3_star: number | null
  ld_x2: number | null
  ld_df: number | null
  ld_signed_z: number | null
  flagged: boolean
}

export interface LocalIndependenceReport {
  pairs: ItemPairStatistic[]
  q3_star_matrix: (number | null)[][]
  q3_mean: number | null
  critical_value: number | null
  alpha: number
  n_bootstrap: number
  seed: number
  notes: string[]
}

export interface Assumptions {
  unidimensionality: UnidimensionalityReport | null
  /** Absent from the object entirely when no reference model was chosen. */
  local_independence?: LocalIndependenceReport | null
}

/* --- DIF (psychometrics/dif.py) ----------------------------------------- */

export interface MantelHaenszelResult {
  odds_ratio: number | null
  d_dif: number | null
  d_dif_se: number | null
  chi_square: number | null
  p_value: number | null
  ets_class: string | null
  n_reference: number
  n_focal: number
  n_strata: number
  n_strata_used: number
  n_dropped: number
  notes: string[]
}

export interface MantelResult {
  chi_square: number | null
  df: number | null
  p_value: number | null
  smd: number | null
  smd_standardised: number | null
  n_reference: number
  n_focal: number
  n_strata_used: number
  notes: string[]
}

export interface LogisticDIFResult {
  /** From `LogisticDIFResult.flagged` (effect size, not significance). */
  flagged: boolean
  /** From `LogisticDIFResult.is_nonuniform`. */
  is_nonuniform: boolean
  uniform_chi_square: number | null
  uniform_df: number | null
  uniform_p: number | null
  uniform_delta_r2: number | null
  nonuniform_chi_square: number | null
  nonuniform_df: number | null
  nonuniform_p: number | null
  nonuniform_delta_r2: number | null
  total_chi_square: number | null
  total_df: number | null
  total_p: number | null
  total_delta_r2: number | null
  group_coefficient: number | null
  interaction_coefficient: number | null
  n_used: number
  notes: string[]
}

export interface IRTLikelihoodRatioResult {
  chi_square: number | null
  df: number | null
  p_value: number | null
  log_likelihood_free: number | null
  log_likelihood_constrained: number | null
  anchor_item_ids: string[]
  purification_passes: number
  notes: string[]
}

export interface DIFResult {
  item_id: string
  /** From `DIFResult.flagged`. True when any method's own criterion fires. */
  flagged: boolean
  /** From `DIFResult.flagged_by`: raw method names, e.g. `["logistic"]`. */
  flagged_by: string[]
  mantel_haenszel: MantelHaenszelResult | null
  mantel: MantelResult | null
  logistic: LogisticDIFResult | null
  irt_lr: IRTLikelihoodRatioResult | null
  mh_p_adjusted: number | null
  logistic_p_adjusted: number | null
  irt_p_adjusted: number | null
  notes: string[]
}

export interface GroupComparison {
  reference_label: string
  focal_label: string
  n_reference: number
  n_focal: number
  items: DIFResult[]
  anchor_item_ids: string[]
  notes: string[]
}

export interface DIFReport {
  comparisons: GroupComparison[]
  n_persons_used: number
  notes: string[]
}

/* --- person scores (orchestrator._score_summary) ------------------------- */

export interface PersonScoreSummary {
  method: string
  n_scored: number
  n_unscorable: number
  mean?: number | null
  sd?: number | null
  minimum?: number | null
  maximum?: number | null
  percentiles?: Record<string, number | null>
  note?: string
}

/* --- per-model bundle ---------------------------------------------------- */

export interface PerModelDiagnostics {
  item_fit: ItemFitReport | null
  global_fit: GlobalFitResult | null
  reliability: ReliabilityReport | null
}

export interface Diagnostics {
  sample: SampleSummary
  validation: ValidationSummary
  reference_model: string | null
  reference_model_rationale: string
  comparison: ComparisonDossier | null
  assumptions: Assumptions
  /** Keyed by model key; only models that converged appear. */
  per_model: Record<string, PerModelDiagnostics>
  person_scores: PersonScoreSummary | null
  /** Keyed by grouping column name. The whole field is null when DIF never ran. */
  dif: Record<string, DIFReport> | null
  failures: DiagnosticFailure[]
  n_diagnostics_failed: number
  seed: number
  elapsed_seconds: number | null
}
