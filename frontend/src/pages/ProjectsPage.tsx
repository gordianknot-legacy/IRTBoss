import { useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'

import { ApiError } from '@/api/client'
import { useCreateProject, useProjects } from '@/api/hooks'
import type { IntendedUse, StakesLevel } from '@/api/types'
import {
  Badge,
  Button,
  Callout,
  EmptyState,
  Field,
  Panel,
  Spinner,
  inputClass,
} from '@/components/ui'
import { formatTimestamp } from '@/lib/format'

/**
 * Stakes and intended use are recorded on the project because the same fit
 * statistic means different things in a research pilot and a certification
 * exam. The API stores them; this screen states why they are being asked for.
 */
const STAKES: { value: StakesLevel; label: string; blurb: string }[] = [
  { value: 'low', label: 'Low', blurb: 'Classroom, formative, or exploratory use.' },
  { value: 'medium', label: 'Medium', blurb: 'Programme monitoring or placement.' },
  { value: 'high', label: 'High', blurb: 'Decisions about individuals that are hard to reverse.' },
]

const USES: { value: IntendedUse; label: string; blurb: string }[] = [
  { value: 'research', label: 'Research', blurb: 'Group-level inference, no individual decisions.' },
  { value: 'operational', label: 'Operational', blurb: 'Routine scoring and reporting.' },
  { value: 'certification', label: 'Certification', blurb: 'Pass/fail against a standard.' },
]

const STAKES_TONE = { low: 'neutral', medium: 'accent', high: 'attention' } as const

export function ProjectsPage() {
  const { data: projects, isPending, error } = useProjects()
  const create = useCreateProject()
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [stakes, setStakes] = useState<StakesLevel>('medium')
  const [use, setUse] = useState<IntendedUse>('operational')

  function submit(event: FormEvent) {
    event.preventDefault()
    create.mutate(
      {
        name,
        description: description.trim() === '' ? null : description,
        stakes_level: stakes,
        intended_use: use,
      },
      {
        onSuccess: () => {
          setOpen(false)
          setName('')
          setDescription('')
        },
      },
    )
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="eyebrow">Workspace</p>
          <h1 className="font-display text-display text-ink">Projects</h1>
        </div>
        <Button onClick={() => setOpen((v) => !v)}>
          {open ? 'Cancel' : 'New project'}
        </Button>
      </div>

      {open && (
        <Panel title="New project" eyebrow="Create">
          <form onSubmit={submit} className="grid gap-4 md:grid-cols-2">
            <div className="space-y-4 md:col-span-2">
              <Field label="Name" htmlFor="name">
                <input
                  id="name"
                  required
                  maxLength={200}
                  className={inputClass}
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                />
              </Field>
              <Field label="Description" htmlFor="description" hint="Optional.">
                <textarea
                  id="description"
                  rows={2}
                  maxLength={5000}
                  className={inputClass}
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                />
              </Field>
            </div>

            <fieldset className="space-y-2">
              <legend className="text-small font-semibold text-ink">Stakes</legend>
              <p className="text-small text-ink-muted">
                What follows from a score. Recorded on the project so the report can
                be read against the decision it supports.
              </p>
              {STAKES.map((option) => (
                <label key={option.value} className="flex cursor-pointer gap-2 text-small">
                  <input
                    type="radio"
                    name="stakes"
                    className="mt-1"
                    checked={stakes === option.value}
                    onChange={() => setStakes(option.value)}
                  />
                  <span>
                    <span className="font-semibold text-ink">{option.label}</span>
                    <span className="block text-ink-muted">{option.blurb}</span>
                  </span>
                </label>
              ))}
            </fieldset>

            <fieldset className="space-y-2">
              <legend className="text-small font-semibold text-ink">Intended use</legend>
              <p className="text-small text-ink-muted">
                What the scores are for.
              </p>
              {USES.map((option) => (
                <label key={option.value} className="flex cursor-pointer gap-2 text-small">
                  <input
                    type="radio"
                    name="use"
                    className="mt-1"
                    checked={use === option.value}
                    onChange={() => setUse(option.value)}
                  />
                  <span>
                    <span className="font-semibold text-ink">{option.label}</span>
                    <span className="block text-ink-muted">{option.blurb}</span>
                  </span>
                </label>
              ))}
            </fieldset>

            {create.error != null && (
              <div className="md:col-span-2">
                <Callout tone="alarm" title="Could not create the project">
                  {create.error instanceof ApiError
                    ? create.error.detail
                    : (create.error as Error).message}
                </Callout>
              </div>
            )}

            <div className="md:col-span-2">
              <Button type="submit" disabled={create.isPending}>
                {create.isPending ? 'Creating…' : 'Create project'}
              </Button>
            </div>
          </form>
        </Panel>
      )}

      {isPending && <Spinner label="Loading projects…" />}
      {error != null && (
        <Callout tone="alarm" title="Could not load projects">
          {(error as Error).message}
        </Callout>
      )}

      {projects != null && projects.length === 0 && (
        <EmptyState title="No projects yet">
          A project holds datasets and the analyses run against them.
        </EmptyState>
      )}

      {projects != null && projects.length > 0 && (
        <ul className="grid gap-3 md:grid-cols-2">
          {projects.map((project) => (
            <li key={project.id}>
              <Link
                to={`/projects/${project.id}`}
                className="block h-full rounded-lg border border-rule bg-surface p-4 shadow-card transition-colors hover:border-accent"
              >
                <div className="flex items-start justify-between gap-3">
                  <h2 className="font-display text-title text-ink">{project.name}</h2>
                  <Badge tone={STAKES_TONE[project.stakes_level]}>
                    {project.stakes_level} stakes
                  </Badge>
                </div>
                {project.description != null && project.description !== '' && (
                  <p className="mt-2 max-w-prose text-small text-ink-muted">
                    {project.description}
                  </p>
                )}
                <p className="mt-3 text-small text-ink-faint">
                  {project.intended_use} · created {formatTimestamp(project.created_at)}
                </p>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
