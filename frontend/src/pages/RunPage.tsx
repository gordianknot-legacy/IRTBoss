import { Link, useParams } from 'react-router-dom'

import { useResults, useRun } from '@/api/hooks'
import { MODEL_LABELS, type ModelKey } from '@/api/types'
import { RunStatusBadge } from '@/components/RunStatusBadge'
import { Callout, Notes, Panel, Spinner } from '@/components/ui'
import { Results } from '@/results/Results'
import { formatTimestamp } from '@/lib/format'

export function RunPage() {
  const { runId = '' } = useParams()
  const run = useRun(runId)
  const succeeded = run.data?.status === 'succeeded'
  const results = useResults(runId, succeeded)

  return (
    <div className="space-y-5">
      <nav className="text-small text-ink-muted">
        {run.data != null && (
          <>
            <Link
              to={`/datasets/${run.data.dataset_id}`}
              className="text-accent hover:underline"
            >
              Dataset
            </Link>
            <span className="px-2">/</span>
          </>
        )}
        <span>Analysis run</span>
      </nav>

      {run.isPending && <Spinner label="Loading run…" />}
      {run.error != null && (
        <Callout tone="alarm" title="Could not load the run">
          {(run.error as Error).message}
        </Callout>
      )}

      {run.data != null && (
        <>
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div>
              <p className="eyebrow">Analysis</p>
              <h1 className="font-display text-display text-ink">
                {run.data.requested_models
                  .map((m) => MODEL_LABELS[m as ModelKey] ?? m)
                  .join(' · ')}
              </h1>
              <p className="mt-1 text-small text-ink-muted">
                Requested {formatTimestamp(run.data.created_at)} · seed{' '}
                <span className="numeric">{run.data.seed}</span> · engine{' '}
                <span className="numeric">{run.data.engine_version}</span>
              </p>
            </div>
            <RunStatusBadge status={run.data.status} />
          </div>

          {(run.data.status === 'queued' || run.data.status === 'running') && (
            <Panel title="In progress" eyebrow="Status">
              <div className="space-y-3">
                <Spinner
                  label={
                    run.data.status === 'queued'
                      ? 'Queued. Waiting for a worker to pick this up.'
                      : 'Running. Fitting each model, then every diagnostic in turn.'
                  }
                />
                <p className="max-w-prose text-small text-ink-muted">
                  Cross-validation refits every model once per fold, so a comparison of
                  several models on a large sample is the slow part. This page polls the
                  durable run record every two seconds; it is safe to leave and come back.
                </p>
                {run.data.notes.length > 0 && <Notes notes={run.data.notes} />}
              </div>
            </Panel>
          )}

          {run.data.status === 'failed' && (
            <Panel title="This run failed" eyebrow="Status">
              <div className="space-y-4">
                <Callout tone="alarm" title="No results were produced">
                  {run.data.failure_reason ??
                    'The run failed and recorded no reason. Nothing partial was kept: ' +
                      'there is no results document for a failed run, because that ' +
                      'document would be a page of absent numbers presented as findings.'}
                </Callout>
                {run.data.notes.length > 0 && <Notes notes={run.data.notes} />}
                <p className="max-w-prose text-small text-ink-muted">
                  Failure reasons shown here are the operator-safe phrase the API stores.
                  The full traceback is in the worker log, not in this response.
                </p>
              </div>
            </Panel>
          )}

          {succeeded && results.isPending && <Spinner label="Loading results…" />}
          {succeeded && results.error != null && (
            <Callout tone="alarm" title="Could not load results">
              {(results.error as Error).message}
            </Callout>
          )}
          {results.data != null && <Results result={results.data} />}
        </>
      )}
    </div>
  )
}
