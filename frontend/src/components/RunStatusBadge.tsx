import type { RunStatus } from '@/api/types'
import { Badge, type BadgeTone } from './ui'

const TONE: Record<RunStatus, BadgeTone> = {
  queued: 'neutral',
  running: 'accent',
  succeeded: 'steady',
  failed: 'alarm',
}

const LABEL: Record<RunStatus, string> = {
  queued: 'queued',
  running: 'running',
  succeeded: 'succeeded',
  failed: 'failed',
}

export function RunStatusBadge({ status }: { status: RunStatus }) {
  return <Badge tone={TONE[status]}>{LABEL[status]}</Badge>
}
