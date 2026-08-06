/**
 * The results screen.
 *
 * Reading order is deliberate and is the argument the product makes:
 *
 *   1. what could not be computed        (failures — before any statistic)
 *   2. what the analysis decided for you (run notes, validation, reference model)
 *   3. the comparison dossier            (no winner)
 *   4. assumptions                       (are the models applicable at all)
 *   5. per-model diagnostics             (fit, reliability)
 *   6. DIF                               (a screen, framed as one)
 *   7. person scores
 *   8. reproducibility
 *
 * Failures come first because a report that leads with statistics and buries
 * "three diagnostics did not run" at the bottom is a report that will be read as
 * complete.
 */

import { useState } from 'react'

import type { AnalysisResult, ModelKey } from '@/api/types'
import { MODEL_LABELS, modelLabel } from '@/api/types'
import { Callout, Notes, Panel } from '@/components/ui'
import { AssumptionsSection } from './AssumptionsSection'
import { ComparisonSection } from './ComparisonSection'
import { DifSection } from './DifSection'
import { FailuresSection } from './FailuresSection'
import { PerModelSection } from './PerModelSection'
import { PersonScoresSection } from './PersonScoresSection'
import { ReproducibilitySection } from './ReproducibilitySection'
import { SampleSection } from './SampleSection'

const SECTIONS = [
  { id: 'coverage', label: 'What was not computed' },
  { id: 'sample', label: 'Sample & validation' },
  { id: 'comparison', label: 'Model comparison' },
  { id: 'assumptions', label: 'Assumptions' },
  { id: 'per-model', label: 'Fit & reliability' },
  { id: 'dif', label: 'Differential item functioning' },
  { id: 'scores', label: 'Person scores' },
  { id: 'repro', label: 'Reproducibility' },
]

export function Results({ result }: { result: AnalysisResult }) {
  const { run, fits, diagnostics } = result

  // Hooks before any early return: `diagnostics` can be null and the branch
  // below returns, so the state has to be declared unconditionally.
  const modelKeys = Object.keys(diagnostics?.per_model ?? {})
  const [selectedModel, setSelectedModel] = useState<string | null>(null)
  const activeModel =
    selectedModel ?? diagnostics?.reference_model ?? modelKeys[0] ?? ''

  if (diagnostics == null) {
    return (
      <Panel title="No diagnostics" eyebrow="Results">
        <Callout tone="absent" title="This run succeeded but stored no diagnostics payload">
          Nothing is being shown in its place. An empty results page would read as
          “diagnostics were computed and found nothing”, which is a different claim
          from “no diagnostics exist”.
        </Callout>
      </Panel>
    )
  }

  return (
    <div className="space-y-6">
      <nav
        aria-label="Report sections"
        className="sticky top-[3.6rem] z-[5] -mx-5 overflow-x-auto border-y border-rule bg-canvas/95 px-5 py-2 backdrop-blur"
      >
        <ul className="flex gap-4 whitespace-nowrap">
          {SECTIONS.map((section) => (
            <li key={section.id}>
              <a
                href={`#${section.id}`}
                className="text-small text-ink-muted hover:text-accent hover:underline"
              >
                {section.label}
              </a>
            </li>
          ))}
        </ul>
      </nav>

      <FailuresSection
        id="coverage"
        failures={diagnostics.failures}
        nFailed={diagnostics.n_diagnostics_failed}
      />

      <Panel id="sample" title="What this run decided" eyebrow="Read first">
        <div className="space-y-5">
          <Notes
            notes={run.notes}
            title="Run notes"
            emptyMessage="The run recorded no notes. That is unusual: validation, applicability and the reference-model choice normally each leave one."
          />

          <div className="space-y-2">
            <p className="eyebrow">Reference model for item-level diagnostics</p>
            {diagnostics.reference_model == null ? (
              <Callout tone="absent" title="No reference model was chosen">
                {diagnostics.reference_model_rationale}
              </Callout>
            ) : (
              <Callout
                tone="accent"
                title={`${modelLabel(diagnostics.reference_model)} — a vantage point, not a verdict`}
              >
                {diagnostics.reference_model_rationale}
              </Callout>
            )}
          </div>

          <SampleSection sample={diagnostics.sample} validation={diagnostics.validation} />
        </div>
      </Panel>

      <ComparisonSection id="comparison" dossier={diagnostics.comparison} fits={fits} />

      <AssumptionsSection
        id="assumptions"
        assumptions={diagnostics.assumptions}
        referenceModel={diagnostics.reference_model}
      />

      <Panel
        id="per-model"
        title="Fit and reliability, per model"
        eyebrow="Diagnostics"
        description={
          <>
            Item fit, global fit and reliability are computed separately for every
            model that converged. Switching models here changes the parameterisation
            the residuals are measured against — which is precisely why the flags
            are not a property of the items.
          </>
        }
        actions={
          modelKeys.length > 1 ? (
            <div className="flex flex-wrap gap-1 rounded bg-sunken p-1">
              {modelKeys.map((key) => (
                <button
                  key={key}
                  type="button"
                  onClick={() => setSelectedModel(key)}
                  className={
                    'rounded px-3 py-1 text-small font-semibold transition-colors ' +
                    (activeModel === key
                      ? 'bg-surface text-ink shadow-card'
                      : 'text-ink-muted hover:text-ink')
                  }
                >
                  {MODEL_LABELS[key as ModelKey] ?? key}
                  {key === diagnostics.reference_model && (
                    <span className="ml-1 text-micro font-normal text-accent">ref</span>
                  )}
                </button>
              ))}
            </div>
          ) : undefined
        }
      >
        <PerModelSection
          modelKey={activeModel}
          diagnostics={diagnostics.per_model[activeModel] ?? null}
          fit={fits.find((f) => f.model_key === activeModel) ?? null}
          isReference={activeModel === diagnostics.reference_model}
        />
      </Panel>

      <DifSection
        id="dif"
        dif={diagnostics.dif}
        referenceModel={diagnostics.reference_model}
      />

      <PersonScoresSection
        id="scores"
        scores={diagnostics.person_scores}
        referenceModel={diagnostics.reference_model}
      />

      <ReproducibilitySection id="repro" run={run} diagnostics={diagnostics} fits={fits} />
    </div>
  )
}
