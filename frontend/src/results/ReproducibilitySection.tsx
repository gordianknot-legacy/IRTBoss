import { useDataset } from '@/api/hooks'
import type { AnalysisRun, Diagnostics, ModelFit } from '@/api/types'
import { modelLabel } from '@/api/types'
import { NumCell, Stat } from '@/components/Value'
import { Badge, Panel, Table, Th } from '@/components/ui'
import { present, presentCount } from '@/lib/absence'
import { formatDuration, formatTimestamp } from '@/lib/format'

/**
 * Everything needed to reproduce this run, as a section of the report rather
 * than a footer. The seed, the engine version and the dataset checksum together
 * are what make a second run comparable to this one; a number quoted without
 * them is a number that cannot be checked.
 */
export function ReproducibilitySection({
  id,
  run,
  diagnostics,
  fits,
}: {
  id: string
  run: AnalysisRun
  diagnostics: Diagnostics
  fits: ModelFit[]
}) {
  const dataset = useDataset(run.dataset_id)

  return (
    <Panel
      id={id}
      title="Reproducibility"
      eyebrow="How to get this report again"
      description="A statistic without the seed, engine version and input checksum that produced it cannot be checked by anyone, including you."
    >
      <div className="space-y-5">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Stat label="Seed" presented={presentCount(diagnostics.seed)} />
          <div className="flex flex-col gap-1 border-l-2 border-rule pl-3">
            <span className="eyebrow">Engine version</span>
            <span className="numeric text-lede font-semibold">{run.engine_version}</span>
          </div>
          <Stat
            label="Analysis wall time"
            presented={present(diagnostics.elapsed_seconds, { places: 2, suffix: ' s' })}
            hint={formatDuration(diagnostics.elapsed_seconds)}
          />
          <Stat
            label="Diagnostics failed"
            presented={presentCount(diagnostics.n_diagnostics_failed)}
            hint={
              diagnostics.n_diagnostics_failed > 0
                ? 'Listed in full at the top of this report.'
                : undefined
            }
          />
        </div>

        <dl className="grid gap-4 sm:grid-cols-2">
          <div>
            <dt className="eyebrow">Dataset</dt>
            <dd className="mt-1 text-small">
              {dataset.data == null ? (
                <span className="text-ink-muted">loading…</span>
              ) : (
                <>
                  {dataset.data.original_filename} ·{' '}
                  {dataset.data.n_persons.toLocaleString('en-GB')} rows ×{' '}
                  {dataset.data.n_items} item columns
                </>
              )}
            </dd>
          </div>
          <div>
            <dt className="eyebrow">SHA-256 of the uploaded bytes</dt>
            <dd className="mt-1 break-all font-mono text-small">
              {dataset.data?.checksum_sha256 ?? (
                <span className="text-ink-muted">loading…</span>
              )}
            </dd>
          </div>
          <div>
            <dt className="eyebrow">Requested models</dt>
            <dd className="mt-1 flex flex-wrap gap-1">
              {run.requested_models.map((key) => (
                <Badge key={key} tone="neutral">
                  {modelLabel(key)}
                </Badge>
              ))}
            </dd>
          </div>
          <div>
            <dt className="eyebrow">Reference model</dt>
            <dd className="mt-1 text-small">
              {diagnostics.reference_model == null ? (
                <span className="text-absent">none — no model converged</span>
              ) : (
                modelLabel(diagnostics.reference_model)
              )}
            </dd>
          </div>
          <div>
            <dt className="eyebrow">Timestamps</dt>
            <dd className="mt-1 space-y-px text-small text-ink-muted">
              <p>requested {formatTimestamp(run.created_at)}</p>
              <p>started {formatTimestamp(run.started_at)}</p>
              <p>finished {formatTimestamp(run.finished_at)}</p>
            </dd>
          </div>
          <div>
            <dt className="eyebrow">Run id</dt>
            <dd className="mt-1 break-all font-mono text-small">{run.id}</dd>
          </div>
        </dl>

        <div className="space-y-2">
          <p className="eyebrow">Per-model estimation record</p>
          <Table
            head={
              <tr>
                <Th align="left">Model</Th>
                <Th align="left">Converged</Th>
                <Th>Elapsed</Th>
                <Th>Free params</Th>
                <Th align="left">If it failed</Th>
              </tr>
            }
          >
            {fits.map((fit) => (
              <tr key={fit.model_key}>
                <td className="px-3 py-2 text-left">{modelLabel(fit.model_key)}</td>
                <td className="px-3 py-2 text-left">
                  {fit.converged ? (
                    <Badge tone="steady">converged</Badge>
                  ) : (
                    <Badge tone="alarm">did not converge</Badge>
                  )}
                </td>
                <NumCell presented={present(fit.elapsed_seconds, { places: 2, suffix: ' s' })} />
                <NumCell presented={presentCount(fit.n_free_parameters)} />
                <td className="max-w-prose px-3 py-2 text-left text-ink-muted">
                  {fit.failure_reason ?? ''}
                </td>
              </tr>
            ))}
          </Table>
        </div>
      </div>
    </Panel>
  )
}
