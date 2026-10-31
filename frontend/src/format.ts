const relative = new Intl.RelativeTimeFormat(undefined, { numeric: 'auto' })

export function timeAgo(iso: string | null | undefined): string {
  if (!iso) return ''
  const seconds = (new Date(iso).getTime() - Date.now()) / 1000
  if (Number.isNaN(seconds)) return ''
  const steps: [number, Intl.RelativeTimeFormatUnit][] = [
    [60, 'second'],
    [60, 'minute'],
    [24, 'hour'],
    [7, 'day'],
    [4.35, 'week'],
    [12, 'month'],
    [Number.POSITIVE_INFINITY, 'year'],
  ]
  let value = seconds
  for (const [size, unit] of steps) {
    if (Math.abs(value) < size) return relative.format(Math.round(value), unit)
    value /= size
  }
  return ''
}

export function fileSize(bytes: number): string {
  if (!bytes) return ''
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

const PALETTE = [
  '#4f46e5', '#0891b2', '#16a34a', '#d97706', '#dc2626', '#7c3aed',
  '#db2777', '#0d9488', '#65a30d', '#ea580c', '#2563eb', '#9333ea',
]

/** Stable colour per entity type: known types by rank, others by name hash. */
export function colorFor(label: string, rankedLabels: string[]): string {
  const rank = rankedLabels.indexOf(label)
  if (rank >= 0 && rank < PALETTE.length) return PALETTE[rank]
  let hash = 0
  for (const ch of label) hash = (hash * 31 + ch.charCodeAt(0)) | 0
  return PALETTE[Math.abs(hash) % PALETTE.length]
}
