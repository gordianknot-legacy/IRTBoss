/**
 * Presentation helpers for flags that the payload now carries itself.
 *
 * This file used to recompute the flags, because Python `@property` accessors
 * were dropped by `analysis/serialise.to_jsonable` — it walks
 * `dataclasses.fields()`, which returns declared fields only. That was a
 * backend defect and it has been fixed: result classes opt properties in by
 * declaring `JSON_PROPERTIES`, so `flagged`, `flagged_by`, `is_nonuniform`,
 * `essentially_unidimensional`, `usable` and `criteria_agree` are all on the
 * wire.
 *
 * Nothing here re-derives a decision any more, and that is the point. A
 * threshold duplicated in TypeScript is a threshold that silently diverges the
 * first time the backend tunes it, and the divergence shows up as two parts of
 * the same product disagreeing about which items are flagged — with no error
 * anywhere.
 *
 * What remains is genuinely presentational: turning a flag into the *reason*
 * a reader needs to see beside it.
 */

import type { DIFResult, ItemFitResult, LocalIndependenceReport } from '@/api/types'

/** Human labels for the method names `DIFResult.flagged_by` returns. */
const DIF_METHOD_LABELS: Record<string, string> = {
  mantel_haenszel: 'Mantel–Haenszel',
  mantel: 'Mantel (standardised difference)',
  logistic: 'Logistic (ΔR²)',
  irt_lr: 'IRT likelihood ratio',
}

export function difMethodLabels(result: DIFResult): string[] {
  // Unknown keys pass through rather than vanishing: a method added to the
  // backend should show up as its raw name, not as silently nothing.
  return (result.flagged_by ?? []).map((m) => DIF_METHOD_LABELS[m] ?? m)
}

/**
 * Which criteria put an item over the line, so a flag is never shown as a bare
 * boolean. The thresholds quoted here are the ones stated in
 * `itemfit.ItemFitResult.flagged`; they are quoted in prose beside the number
 * that triggered them, not used to decide anything.
 */
export function itemFitReasons(item: ItemFitResult): string[] {
  if (!item.flagged) return []
  const out: string[] = []
  if (item.rmsd != null && item.rmsd > 0.1) {
    out.push(`RMSD ${item.rmsd.toFixed(3)} exceeds 0.10`)
  }
  if (item.infit != null && !(item.infit >= 0.7 && item.infit <= 1.3)) {
    out.push(`infit ${item.infit.toFixed(2)} is outside 0.7–1.3`)
  }
  if (item.outfit != null && !(item.outfit >= 0.7 && item.outfit <= 1.3)) {
    out.push(`outfit ${item.outfit.toFixed(2)} is outside 0.7–1.3`)
  }
  // The flag came from the backend, so an empty list here means the backend's
  // rule and this explanation have drifted apart. Say so rather than showing a
  // flag with no stated cause.
  if (out.length === 0) {
    out.push('Flagged by the fit criteria; see the item statistics above.')
  }
  return out
}

export function localIndependenceFlagged(report: LocalIndependenceReport) {
  return report.pairs.filter((p) => p.flagged)
}

/**
 * The sentence that must travel with each flag. Keyed by the section that shows
 * it; there is no path that renders a flag without one of these nearby.
 */
export const THRESHOLD_NOTES = {
  itemFit:
    'A flag here means an item is worth looking at, not that it is a bad item. ' +
    'The bands are conventions — mean-squares of 0.7–1.3 are the productive ' +
    'range for a moderate-stakes test, and RMSD above 0.10 is the threshold used ' +
    'in large-scale international assessment. Neither is a law, and both depend ' +
    'on the reference model these residuals were computed against. The band is ' +
    'also porous in one direction: an item that discriminates far better than ' +
    'the model allows produces unusually small residuals and can pass while ' +
    'genuinely misfitting, which is why S-X² is reported alongside.',
  dif:
    'DIF results are a screen, not a verdict. An item flagged here behaves ' +
    'differently between groups conditional on the trait; deciding whether that ' +
    'difference is bias requires knowing what the item is asking, which no ' +
    'statistic in this report can see.',
  localIndependence:
    'A flagged pair shares variance the trait does not explain. That is a reason ' +
    'to read the two items together, not a reason to drop either of them.',
  unidimensionality:
    'These thresholds (one retained factor, ECV above 0.85, omega-hierarchical ' +
    'above 0.80) are the values commonly cited as supporting a single score. ' +
    'Mixed evidence is a real outcome: the components are shown so the reader ' +
    'can weigh them.',
} as const
