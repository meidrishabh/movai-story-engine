/** 670 -> "11:10", 4620 -> "1:17:00". Screen time is shown as a clock, the way a script is timed. */
export function formatDuration(totalSeconds: number | null | undefined): string {
  if (totalSeconds === null || totalSeconds === undefined) return '–'
  const seconds = Math.max(0, Math.round(totalSeconds))
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = seconds % 60
  const pad = (n: number) => String(n).padStart(2, '0')
  return h > 0 ? `${h}:${pad(m)}:${pad(s)}` : `${m}:${pad(s)}`
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return '–'
  return new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
}

export function plural(count: number, one: string, many = `${one}s`): string {
  return `${count} ${count === 1 ? one : many}`
}

/** Minutes for a human estimate: 48 -> "under 1 min", 190 -> "about 4 min". */
export function formatMinutes(seconds: number): string {
  if (seconds < 60) return 'under 1 min'
  return `about ${Math.ceil(seconds / 60)} min`
}
