import { useMemo, useState, type FormEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'

import { ApiError } from '@/api/client'
import { useCreateAnalysis, useDataset, useRuns } from '@/api/hooks'
import { MODEL_KEYS, MODEL_LABELS, POLYTOMOUS_MODELS, type ModelKey } from '@/api/types'
import {
  Badge,
  Button,
  Callout,
  EmptyState,
  Field,
  Panel,
  Spinner,
  Table,
  Th,
  inputClass,
} from '@/components/ui'
import { RunStatusBadge } from '@/components/RunStatusBadge'
import { formatTimestamp, shortChecksum } from '@/lib/format'

/** `AnalysisCreate.seed` default in `backend/app/api/schemas.py`. */
const DEFAULT_SEED = 20260803
/** `AnalysisCreate.models` is `min_length=1, max_length=7`. */
const MAX_MODELS = 7

const MODEL_BLURB: Record<ModelKey, string> = {
  rasch: 'Every slope fixed at 1; the latent variance is estimated. Dichotomous.',
  '1pl': 'One slope common to all items; the latent variance is fixed. Dichotomous.',
  '2pl': 'A slope and a difficulty per item. Dichotomous.',
  '3pl': 'Adds a lower asymptote. Needs roughly 60 items × 1,000 respondents to be stable.',
  grm: 'Ordered categories via cumulative logits. Polytomous.',
  pcm: 'Adjacent-category logits with slopes fixed at 1. Polytomous.',
  gpcm: 'Adjacent-category logits with a free slope per item. Polytomous.',
}

export function DatasetPage() {
  const { datasetId = '' } = useParams()
  const navigate = useNavigate()
  const dataset = useDataset(datasetId)
  const runs = useRuns(datasetId)
  const create = useCreateAnalysis(datasetId)

  const [selected, setSelected] = useState<ModelKey[]>(['rasch', '2pl'])
  const [seed, setSeed] = useState(DEFAULT_SEED)

  /**
   * How many categories the file appears to contain, from the ingest metadata.
   * This is advisory only: the authoritative recoding happens in
   * `analysis/validate.py` in the worker, and it can drop columns this count
   * still includes.
   */
  const maxCategories = useMemo(() => {
    const observed = dataset.data?.column_metadata?.observed_categories
    if (observed == null) return null
    const counts = Object.values(observed).map((values) => values.length)
    return counts.length === 0 ? null : Math.max(...counts)
  }, [dataset.data])

  const looksPolytomous = maxCategories != null && maxCategories > 2

  function toggle(key: ModelKey) {
    setSelected((current) =>
      current.includes(key)
        ? current.filter((k) => k !== key)
        : current.length >= MAX_MODELS
          ? current
          : [...current, key],
    )
  }

  function submit(event: FormEvent) {
    event.preventDefault()
    create.mutate(
      { models: selected, seed },
      { onSuccess: (run) => navigate(`/analyses/${run.id}`) },
    )
  }

  return (
    <div className="space-y-5">
      <nav className="text-small text-ink-muted">
        {dataset.data != null && (
          <>
            <Link
              to={`/projects/${dataset.data.project_id}`}
              className="text-accent hover:underline"
            >
              Project
            </Link>
            <span className="px-2">/</span>
          </>
        )}
        <span>{dataset.data?.original_filename ?? '…'}</span>
      </nav>

      {dataset.isPending && <Spinner label="Loading dataset…" />}
      {dataset.error != null && (
        <Callout tone="alarm" title="Could not load the dataset">
          {(dataset.error as Error).message}
        </Callout>
      )}

      {dataset.data != null && (
        <>
          <div>
            <p className="eyebrow">Dataset</p>
            <h1 className="font-display text-display text-ink">
              {dataset.data.original_filename}
            </h1>
            <p className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-small text-ink-muted">
              <span>
                <span className="numeric">
                  {dataset.data.n_persons.toLocaleString('en-GB')}
                </span>{' '}
                respondents
              </span>
              <span>
                <span className="numeric">{dataset.data.n_items}</span> item columns
              </span>
              <span title={dataset.data.checksum_sha256}>
                sha256 <span className="numeric">{shortChecksum(dataset.data.checksum_sha256)}</span>
              </span>
              <span>uploaded {formatTimestamp(dataset.data.created_at)}</span>
            </p>
          </div>

          <Panel title="Declared columns" eyebrow="As uploaded">
            <dl className="grid gap-4 sm:grid-cols-3">
              <div>
                <dt className="eyebrow">Id column</dt>
                <dd className="mt-1 text-small">
                  {dataset.data.column_metadata.id_column ?? (
                    <span className="text-ink-muted">none declared</span>
                  )}
                </dd>
              </div>
              <div>
                <dt className="eyebrow">Grouping columns</dt>
                <dd className="mt-1 text-small">
                  {dataset.data.column_metadata.group_columns.length === 0 ? (
                    <span className="text-ink-muted">
                      none — DIF cannot be screened for this dataset
                    </span>
                  ) : (
                    dataset.data.column_metadata.group_columns.join(', ')
                  )}
                </dd>
              </div>
              <div>
                <dt className="eyebrow">Observed categories</dt>
                <dd className="mt-1 text-small">
                  {maxCategories == null ? (
                    <span className="text-ink-muted">not recorded</span>
                  ) : (
                    <>
                      up to <span className="numeric">{maxCategories}</span> distinct
                      responses per item
                    </>
                  )}
                </dd>
              </div>
            </dl>
          </Panel>

          <Panel
            title="Run an analysis"
            eyebrow="Models"
            description={
              <>
                Choose the candidates you want compared. The report ranks them by
                held-out predictive log-likelihood <em>with its uncertainty</em>, shows
                where AIC and BIC disagree with it, and does not name a winner.
                Requesting more models costs fold fits, not accuracy.
              </>
            }
          >
            <form onSubmit={submit} className="space-y-4">
              {looksPolytomous && (
                <Callout tone="attention" title="This file looks polytomous">
                  At least one column has {maxCategories} distinct responses. Dichotomous
                  models (Rasch, 1PL, 2PL, 3PL) will be dropped with a note rather than
                  fitted — collapsing categories to right/wrong would discard the
                  distinctions the extra categories were written to capture.
                </Callout>
              )}

              <fieldset className="grid gap-2 sm:grid-cols-2">
                <legend className="sr-only">Models</legend>
                {MODEL_KEYS.map((key) => {
                  const checked = selected.includes(key)
                  const atLimit = !checked && selected.length >= MAX_MODELS
                  return (
                    <label
                      key={key}
                      className={
                        'flex cursor-pointer gap-3 rounded border px-3 py-2 transition-colors ' +
                        (checked ? 'border-accent bg-accent-soft' : 'border-rule bg-raised') +
                        (atLimit ? ' opacity-50' : '')
                      }
                    >
                      <input
                        type="checkbox"
                        className="mt-1"
                        checked={checked}
                        disabled={atLimit}
                        onChange={() => toggle(key)}
                      />
                      <span className="min-w-0">
                        <span className="flex items-center gap-2">
                          <span className="text-small font-semibold text-ink">
                            {MODEL_LABELS[key]}
                          </span>
                          <Badge tone="neutral">
                            {POLYTOMOUS_MODELS.has(key) ? 'polytomous' : 'dichotomous'}
                          </Badge>
                        </span>
                        <span className="block text-small text-ink-muted">
                          {MODEL_BLURB[key]}
                        </span>
                      </span>
                    </label>
                  )
                })}
              </fieldset>

              <div className="grid gap-4 sm:grid-cols-2">
                <Field
                  label="Seed"
                  htmlFor="seed"
                  hint="Fixes the cross-validation folds, the parallel-analysis draws and the local-independence bootstrap. Recorded on the run."
                >
                  <input
                    id="seed"
                    type="number"
                    min={0}
                    max={2 ** 31 - 1}
                    className={inputClass}
                    value={seed}
                    onChange={(e) => setSeed(Number(e.target.value))}
                  />
                </Field>
                <p className="self-end text-small text-ink-muted">
                  {selected.length === 1 &&
                    'One model produces no comparison: a single fit says how well it ' +
                      'describes the data, not whether another would describe it better.'}
                  {selected.length >= 2 &&
                    `${selected.length} models will be cross-validated against each other.`}
                </p>
              </div>

              {create.error != null && (
                <Callout tone="alarm" title="The run was not started">
                  {create.error instanceof ApiError
                    ? create.error.detail
                    : (create.error as Error).message}
                  {create.error instanceof ApiError && create.error.status === 503 && (
                    <p className="mt-2 text-ink-muted">
                      The run has been recorded and can be retried; it is not lost.
                    </p>
                  )}
                </Callout>
              )}

              <Button type="submit" disabled={selected.length === 0 || create.isPending}>
                {create.isPending ? 'Queueing…' : 'Run analysis'}
              </Button>
            </form>
          </Panel>

          <Panel title="Runs" eyebrow="History">
            {runs.isPending && <Spinner label="Loading runs…" />}
            {runs.data != null && runs.data.length === 0 && (
              <EmptyState title="No analyses have been run against this dataset yet." />
            )}
            {runs.data != null && runs.data.length > 0 && (
              <Table
                head={
                  <tr>
                    <Th align="left">Status</Th>
                    <Th align="left">Models</Th>
                    <Th>Seed</Th>
                    <Th align="left">Engine</Th>
                    <Th align="left">Started</Th>
                    <Th align="left"> </Th>
                  </tr>
                }
              >
                {runs.data.map((run) => (
                  <tr key={run.id} className="hover:bg-sunken">
                    <td className="px-3 py-2">
                      <RunStatusBadge status={run.status} />
                    </td>
                    <td className="px-3 py-2 text-left">
                      {run.requested_models.map((m) => MODEL_LABELS[m as ModelKey] ?? m).join(', ')}
                    </td>
                    <td className="numeric px-3 py-2 text-right">{run.seed}</td>
                    <td className="numeric px-3 py-2 text-left text-ink-muted">
                      {run.engine_version}
                    </td>
                    <td className="px-3 py-2 text-left text-ink-muted">
                      {formatTimestamp(run.started_at ?? run.created_at)}
                    </td>
                    <td className="px-3 py-2">
                      <Link
                        to={`/analyses/${run.id}`}
                        className="text-small font-semibold text-accent hover:underline"
                      >
                        Open →
                      </Link>
                    </td>
                  </tr>
                ))}
              </Table>
            )}
          </Panel>
        </>
      )}
    </div>
  )
}
