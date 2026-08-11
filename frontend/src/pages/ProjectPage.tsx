import { useMemo, useState, type FormEvent } from 'react'
import { Link, useParams } from 'react-router-dom'

import { ApiError } from '@/api/client'
import { useDatasets, useProject, useUploadDataset } from '@/api/hooks'
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
import { formatBytes, formatTimestamp, shortChecksum } from '@/lib/format'

/** Reads the header row locally so the id/group pickers are lists, not free text. */
async function readHeader(file: File): Promise<string[]> {
  const slice = await file.slice(0, 64 * 1024).text()
  const firstLine = slice.split(/\r?\n/)[0] ?? ''
  return firstLine
    .split(',')
    .map((c) => c.trim().replace(/^"(.*)"$/, '$1'))
    .filter((c) => c !== '')
}

export function ProjectPage() {
  const { projectId = '' } = useParams()
  const project = useProject(projectId)
  const datasets = useDatasets(projectId)
  const upload = useUploadDataset(projectId)

  const [file, setFile] = useState<File | null>(null)
  const [header, setHeader] = useState<string[]>([])
  const [headerError, setHeaderError] = useState<string | null>(null)
  const [idColumn, setIdColumn] = useState('')
  const [groupColumns, setGroupColumns] = useState<string[]>([])

  const itemColumns = useMemo(
    () => header.filter((c) => c !== idColumn && !groupColumns.includes(c)),
    [header, idColumn, groupColumns],
  )

  async function chooseFile(next: File | null) {
    setFile(next)
    setIdColumn('')
    setGroupColumns([])
    setHeader([])
    setHeaderError(null)
    if (next == null) return
    try {
      const columns = await readHeader(next)
      if (columns.length === 0) {
        setHeaderError('No header row could be read from this file.')
      }
      setHeader(columns)
    } catch {
      setHeaderError(
        'This file’s header could not be read in the browser. You can still upload ' +
          'it — the server does the authoritative parsing — but the column pickers ' +
          'below will be empty.',
      )
    }
  }

  function submit(event: FormEvent) {
    event.preventDefault()
    if (file == null) return
    upload.mutate(
      { file, idColumn: idColumn === '' ? null : idColumn, groupColumns },
      {
        onSuccess: () => {
          setFile(null)
          setHeader([])
          setIdColumn('')
          setGroupColumns([])
        },
      },
    )
  }

  const uploadError = upload.error

  return (
    <div className="space-y-5">
      <nav className="text-small text-ink-muted">
        <Link to="/projects" className="text-accent hover:underline">
          Projects
        </Link>
        <span className="px-2">/</span>
        <span>{project.data?.name ?? '…'}</span>
      </nav>

      {project.isPending && <Spinner label="Loading project…" />}
      {project.data != null && (
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <p className="eyebrow">Project</p>
            <h1 className="font-display text-display text-ink">{project.data.name}</h1>
            {project.data.description != null && project.data.description !== '' && (
              <p className="mt-2 max-w-prose text-body text-ink-muted">
                {project.data.description}
              </p>
            )}
          </div>
          <div className="flex gap-2">
            <Badge tone="attention">{project.data.stakes_level} stakes</Badge>
            <Badge tone="accent">{project.data.intended_use}</Badge>
          </div>
        </div>
      )}

      <Panel
        title="Upload a response matrix"
        eyebrow="Dataset"
        description={
          <>
            One row per respondent, one column per item, raw response codes as
            collected. The id and grouping columns are <strong>declared</strong>,
            never inferred — an id column fitted as an item is a real defect and
            guessing is how it happens.
          </>
        }
      >
        <form onSubmit={submit} className="space-y-4">
          <Field label="CSV file" htmlFor="file">
            <input
              id="file"
              type="file"
              accept=".csv,text/csv"
              className={inputClass}
              onChange={(e) => void chooseFile(e.target.files?.[0] ?? null)}
            />
          </Field>

          {headerError != null && <Callout tone="attention">{headerError}</Callout>}

          {header.length > 0 && (
            <div className="grid gap-4 md:grid-cols-2">
              <Field
                label="Respondent id column"
                htmlFor="id-column"
                hint="Excluded from the item set. Leave as “none” if the file has no id."
              >
                <select
                  id="id-column"
                  className={inputClass}
                  value={idColumn}
                  onChange={(e) => setIdColumn(e.target.value)}
                >
                  <option value="">none — every column is an item</option>
                  {header.map((column) => (
                    <option key={column} value={column}>
                      {column}
                    </option>
                  ))}
                </select>
              </Field>

              <fieldset className="space-y-1">
                <legend className="text-small font-semibold text-ink">
                  Grouping columns
                </legend>
                <p className="text-small text-ink-muted">
                  Each one is screened for differential item functioning. Also
                  excluded from the item set.
                </p>
                <div className="max-h-40 overflow-y-auto rounded border border-rule-strong bg-raised p-2">
                  {header
                    .filter((c) => c !== idColumn)
                    .map((column) => (
                      <label key={column} className="flex items-center gap-2 py-px text-small">
                        <input
                          type="checkbox"
                          checked={groupColumns.includes(column)}
                          onChange={(e) =>
                            setGroupColumns((current) =>
                              e.target.checked
                                ? [...current, column]
                                : current.filter((c) => c !== column),
                            )
                          }
                        />
                        {column}
                      </label>
                    ))}
                </div>
              </fieldset>

              <p className="text-small text-ink-muted md:col-span-2">
                {itemColumns.length} of {header.length} columns will be treated as
                items.{' '}
                {itemColumns.length === 0 &&
                  'The server will reject this: no item columns remain.'}
              </p>
            </div>
          )}

          {uploadError != null && (
            <Callout tone="alarm" title="The upload was rejected">
              <p>
                {uploadError instanceof ApiError
                  ? uploadError.detail
                  : (uploadError as Error).message}
              </p>
              {uploadError instanceof ApiError && uploadError.fieldErrors.length > 0 && (
                <ul className="mt-2 list-disc pl-4">
                  {uploadError.fieldErrors.map((f) => (
                    <li key={f.field}>
                      <code className="font-mono">{f.field}</code> — {f.message}
                    </li>
                  ))}
                </ul>
              )}
              <p className="mt-2 text-ink-muted">
                These messages are written by the ingest layer for you to act on.
                Nothing was stored.
              </p>
            </Callout>
          )}

          <Button type="submit" disabled={file == null || upload.isPending}>
            {upload.isPending ? 'Uploading…' : 'Upload dataset'}
          </Button>
        </form>
      </Panel>

      <Panel title="Datasets" eyebrow="Uploaded">
        {datasets.isPending && <Spinner label="Loading datasets…" />}
        {datasets.data != null && datasets.data.length === 0 && (
          <EmptyState title="No datasets yet">
            Upload a CSV above to run an analysis against it.
          </EmptyState>
        )}
        {datasets.data != null && datasets.data.length > 0 && (
          <Table
            head={
              <tr>
                <Th align="left">File</Th>
                <Th>Respondents</Th>
                <Th>Items</Th>
                <Th>Size</Th>
                <Th align="left">SHA-256</Th>
                <Th align="left">Uploaded</Th>
                <Th align="left"> </Th>
              </tr>
            }
          >
            {datasets.data.map((dataset) => (
              <tr key={dataset.id} className="hover:bg-sunken">
                <td className="px-3 py-2 text-left">{dataset.original_filename}</td>
                <td className="numeric px-3 py-2 text-right">
                  {dataset.n_persons.toLocaleString('en-GB')}
                </td>
                <td className="numeric px-3 py-2 text-right">{dataset.n_items}</td>
                <td className="numeric px-3 py-2 text-right">
                  {formatBytes(dataset.size_bytes)}
                </td>
                <td
                  className="numeric px-3 py-2 text-left text-ink-muted"
                  title={dataset.checksum_sha256}
                >
                  {shortChecksum(dataset.checksum_sha256)}
                </td>
                <td className="px-3 py-2 text-left text-ink-muted">
                  {formatTimestamp(dataset.created_at)}
                </td>
                <td className="px-3 py-2 text-left">
                  <Link
                    to={`/datasets/${dataset.id}`}
                    className="text-small font-semibold text-accent hover:underline"
                  >
                    Analyse →
                  </Link>
                </td>
              </tr>
            ))}
          </Table>
        )}
      </Panel>
    </div>
  )
}
