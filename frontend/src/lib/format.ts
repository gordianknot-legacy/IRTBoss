import { clsx, type ClassValue } from 'clsx'

export function cn(...values: ClassValue[]): string {
  return clsx(values)
}

export function formatTimestamp(iso: string | null | undefined): string {
  if (!iso) return 'not recorded'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return 'not recorded'
  return date.toLocaleString('en-GB', {
    year: 'numeric',
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds)) return 'not recorded'
  if (seconds < 1) return `${Math.round(seconds * 1000)} ms`
  if (seconds < 60) return `${seconds.toFixed(1)} s`
  const minutes = Math.floor(seconds / 60)
  return `${minutes} min ${Math.round(seconds % 60)} s`
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

/** Checksums are quoted in full on the reproducibility panel and elided elsewhere. */
export function shortChecksum(checksum: string): string {
  return checksum.length <= 16 ? checksum : `${checksum.slice(0, 12)}…${checksum.slice(-4)}`
}
