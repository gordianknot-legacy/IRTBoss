import type { DiagnosticFailure } from '@/api/types'
import { Callout, Panel } from '@/components/ui'

/**
 * `diagnostics.failures` and `n_diagnostics_failed`, at the top of the report.
 *
 * A failed diagnostic does not fail the run — that is deliberate in the
 * orchestrator, because one statistic raising is a reason to omit that claim,
 * not to discard every other. The consequence is that a successful run can be
 * missing several sections, and the only defence against reading it as complete
 * is to say so before the first number.
 */
export function FailuresSection({
  id,
  failures,
  nFailed,
}: {
  id: string
  failures: DiagnosticFailure[]
  nFailed: number
}) {
  if (nFailed === 0 && failures.length === 0) {
    return (
      <Panel id={id} title="Diagnostic coverage" eyebrow="Completeness">
        <Callout tone="steady" title="Every attempted diagnostic completed">
          Nothing in this report is missing because a computation failed. Individual
          statistics can still be absent — a test with no degrees of freedom, a
          standard error that could not be estimated — and those are marked
          “not computed” where they occur.
        </Callout>
      </Panel>
    )
  }

  // The count is the authority; the list is what the report can name. If they
  // disagree, that gap is itself reportable.
  const unlisted = nFailed - failures.length

  return (
    <Panel id={id} title="Diagnostic coverage" eyebrow="Completeness">
      <div className="space-y-4">
        <Callout
          tone="alarm"
          title={`${nFailed} diagnostic${nFailed === 1 ? '' : 's'} could not be computed`}
        >
          The statistics they would have produced are absent from this report. They
          are not zero and they are not reassuring — read the rest of the report as
          missing these claims entirely.
        </Callout>

        <ul className="divide-y divide-rule rounded border border-rule">
          {failures.map((failure, index) => (
            <li key={`${failure.diagnostic}-${index}`} className="px-4 py-3">
              <p className="numeric text-small font-semibold text-ink">
                {failure.diagnostic}
              </p>
              <p className="mt-1 max-w-prose font-mono text-small text-alarm">
                {failure.error}
              </p>
            </li>
          ))}
        </ul>

        {unlisted > 0 && (
          <Callout tone="absent" title={`${unlisted} further failure(s) are counted but not listed`}>
            The run recorded {nFailed} failures and named {failures.length}. The
            difference is unexplained by this payload.
          </Callout>
        )}

        <p className="max-w-prose text-small text-ink-muted">
          Each failure is a one-line summary. The full traceback is in the worker log
          and is deliberately not returned to this client.
        </p>
      </div>
    </Panel>
  )
}
