import { Badge, Card, Empty, ErrorNote, Loading, PageHeader } from '../../shared/ui'
import { formatDuration, plural } from '../../shared/lib/format'
import { useSeriesId } from '../series/api'
import { useContinuity, useMasterScript, useTimeline } from './api'
import type { Anchor, StoryEvent } from './types'

const SEVERITY_TONE: Record<string, 'bad' | 'warn' | 'neutral'> = { high: 'bad', medium: 'warn', low: 'neutral' }

export default function StructurePage() {
  const seriesId = useSeriesId()
  const timeline = useTimeline(seriesId)
  const continuity = useContinuity(seriesId)
  const script = useMasterScript(seriesId)

  if (timeline.isPending || continuity.isPending || script.isPending) return <Loading />
  if (timeline.isError) return <div className="page"><ErrorNote error={timeline.error} onRetry={() => void timeline.refetch()} /></div>
  if (continuity.isError) return <div className="page"><ErrorNote error={continuity.error} onRetry={() => void continuity.refetch()} /></div>

  const { anchors, events } = timeline.data
  const { conflicts } = continuity.data
  const units = script.data?.units ?? []
  const loose = events.filter((e) => !anchors.some((a) => a.id === e.timeline_anchor_id))

  if (events.length === 0 && units.length === 0) {
    return (
      <div className="page">
        <PageHeader title="Story structure" />
        <Empty title="No structure yet">The timeline and master script appear when the analysis finishes.</Empty>
      </div>
    )
  }

  return (
    <div className="page">
      <PageHeader title="Story structure" subtitle="What happens, in what order, and where the story contradicts itself." />

      <div className="stack">
        <div className="row">
          <h2>Continuity</h2>
          <Badge tone={conflicts.length ? 'warn' : 'ok'}>{conflicts.length ? plural(conflicts.length, 'conflict') : 'no conflicts'}</Badge>
        </div>
        {conflicts.map((c) => (
          <Card key={c.id}>
            <div className="row">
              <Badge tone={SEVERITY_TONE[c.severity] ?? 'neutral'}>{c.severity}</Badge>
              <Badge>{c.conflict_type.replace(/_/g, ' ')}</Badge>
              <span className="muted">{c.entity_type}</span>
            </div>
            <p>{c.description}</p>
          </Card>
        ))}
      </div>

      <div className="stack">
        <div className="row">
          <h2>Timeline</h2>
          <Badge>{plural(events.length, 'event')}</Badge>
        </div>
        {anchors.map((a) => (
          <AnchorGroup key={a.id} anchor={a} events={events.filter((e) => e.timeline_anchor_id === a.id)} />
        ))}
        {loose.length > 0 && <EventList events={loose} />}
      </div>

      <div className="stack">
        <div className="row">
          <h2>Master script</h2>
          {script.data && <Badge>version {script.data.version_number}</Badge>}
          <Badge>{plural(units.length, 'unit')}</Badge>
        </div>
        {script.data?.summary && <p className="muted">{script.data.summary}</p>}
        {units.map((u) => (
          <Card key={u.id}>
            <div className="row row-between">
              <strong>
                {u.sequence_number}. {u.title}
              </strong>
              <span className="muted mono">{formatDuration(u.estimated_seconds)}</span>
            </div>
            {u.synopsis && <p className="muted">{u.synopsis}</p>}
            <div className="row">
              {(u.character_names ?? []).map((n) => (
                <Badge key={`c-${n}`} tone="accent">{n}</Badge>
              ))}
              {(u.location_names ?? []).map((n) => (
                <Badge key={`l-${n}`}>{n}</Badge>
              ))}
            </div>
          </Card>
        ))}
      </div>
    </div>
  )
}

function AnchorGroup({ anchor, events }: { anchor: Anchor; events: StoryEvent[] }) {
  return (
    <Card>
      <div className="row">
        <strong>{anchor.label}</strong>
        {anchor.timeline_type && <Badge>{anchor.timeline_type}</Badge>}
      </div>
      {anchor.description && <p className="muted">{anchor.description}</p>}
      {events.length > 0 && <EventList events={events} />}
    </Card>
  )
}

function EventList({ events }: { events: StoryEvent[] }) {
  return (
    <ol className="event-list">
      {events.map((e) => (
        <li key={e.id}>
          <strong>{e.title}</strong>
          {e.description && <span className="muted"> · {e.description}</span>}
        </li>
      ))}
    </ol>
  )
}
