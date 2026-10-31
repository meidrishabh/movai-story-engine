import type { ReactNode } from 'react'

import { Badge, Button, Card, Empty, ErrorNote, Loading, Notice, PageHeader } from '../../shared/ui'
import { formatDuration, plural } from '../../shared/lib/format'
import { useSeriesId } from '../series/api'
import { useAdaptations, useBeatDecision, useGenerate } from './api'
import { BeatRow } from './BeatRow'
import type { AdaptationItem, BeatAction, BeatItem } from './types'

const beatKey = (item: BeatItem) => `${item.unit}:${item.beat ?? 'unit'}`

export default function AdaptationPage() {
  const seriesId = useSeriesId()
  const adaptations = useAdaptations(seriesId)
  const decide = useBeatDecision(seriesId)
  const generate = useGenerate(seriesId)

  if (adaptations.isPending) return <Loading />
  if (adaptations.isError) return <div className="page"><ErrorNote error={adaptations.error} onRetry={() => void adaptations.refetch()} /></div>

  const items = adaptations.data
  const full = items.find((i) => i.kind === 'full')
  const concentrated = items.find((i) => i.kind === 'concentrated')
  const extras = items.filter((i) => i.group === 'extra')

  if (!full?.available) {
    return (
      <div className="page">
        <PageHeader title="Adaptation" />
        <Empty title="The master script is not ready yet">Run the analysis first; the adaptation options appear when it finishes.</Empty>
      </div>
    )
  }

  const removed = concentrated?.removed ?? []
  const disputed = concentrated?.disputed ?? []
  const restored = concentrated?.restored ?? []
  const pendingKey = decide.isPending && decide.variables ? `${decide.variables.unit}:${decide.variables.beat ?? 'unit'}` : null

  function onDecide(item: BeatItem, action: BeatAction) {
    decide.mutate({ unit: item.unit, beat: item.beat, action })
  }

  return (
    <div className="page">
      <PageHeader title="Adaptation" subtitle="Episodes are planned from the concentrated version: the same story without filler. Every cut can be undone." />

      <div className="tiles">
        <Tile
          label="Adaptation length"
          value={formatDuration(concentrated?.available ? concentrated.duration_seconds : full.duration_seconds)}
          note={concentrated?.available ? `${formatDuration(concentrated.saved_seconds)} of filler removed` : 'Filler review not run yet'}
        />
      </div>

      {decide.isError && <ErrorNote error={decide.error} />}
      {decide.isSuccess && decide.data.affected_episodes.length > 0 && (
        <Notice>
          Saved. {plural(decide.data.affected_episodes.length, 'episode')} will be refreshed so the story still flows; their scene
          breakdowns are marked out of date.
        </Notice>
      )}
      {decide.isSuccess && decide.data.affected_episodes.length === 0 && <Notice>Saved.</Notice>}
      {decide.isSuccess && decide.data.replan_job && <Notice tone="warn">Your draft episode plans are being rebuilt from the new cut.</Notice>}

      <Section title="Removed as filler" count={removed.length} empty="Nothing was removed.">
        {removed.map((item) => (
          <BeatRow key={beatKey(item)} item={item} variant="removed" busy={pendingKey === beatKey(item)} onDecide={(a) => onDecide(item, a)} />
        ))}
      </Section>

      <Section title="Needs your decision" count={disputed.length} empty="No beats are in dispute.">
        {disputed.map((item) => (
          <BeatRow key={beatKey(item)} item={item} variant="disputed" busy={pendingKey === beatKey(item)} onDecide={(a) => onDecide(item, a)} />
        ))}
      </Section>

      {restored.length > 0 && (
        <Section title="Kept by you" count={restored.length} empty="">
          {restored.map((item) => (
            <BeatRow key={beatKey(item)} item={item} variant="restored" busy={pendingKey === beatKey(item)} onDecide={(a) => onDecide(item, a)} />
          ))}
        </Section>
      )}

      <div className="stack">
        <h2>Trailer and teaser</h2>
        <div className="grid">
          {extras.map((extra) => (
            <ExtraCard key={extra.kind} item={extra} busy={generate.isPending} onGenerate={() => generate.mutate({ kind: extra.kind as 'trailer' | 'teaser', target_seconds: extra.target_seconds ?? extra.default_seconds })} />
          ))}
        </div>
        {generate.isError && <ErrorNote error={generate.error} />}
      </div>
    </div>
  )
}

function Tile({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="tile">
      <span className="muted">{label}</span>
      <span className="tile-value">{value}</span>
      {note && <span className="muted">{note}</span>}
    </div>
  )
}

function Section({ title, count, empty, children }: { title: string; count: number; empty: string; children: ReactNode }) {
  return (
    <div className="stack">
      <div className="row">
        <h2>{title}</h2>
        <Badge>{count}</Badge>
      </div>
      {count === 0 ? empty && <p className="muted">{empty}</p> : children}
    </div>
  )
}

function ExtraCard({ item, busy, onGenerate }: { item: AdaptationItem; busy: boolean; onGenerate: () => void }) {
  const generating = item.status === 'generating'
  return (
    <Card>
      <div className="row row-between">
        <h3>{item.label}</h3>
        <Badge tone={item.status === 'ready' ? (item.stale ? 'warn' : 'ok') : item.status === 'failed' ? 'bad' : 'neutral'}>
          {item.stale ? 'Out of date' : item.status.replace('_', ' ')}
        </Badge>
      </div>
      {item.status === 'ready' && item.summary ? (
        <>
          <strong>{item.summary.title}</strong>
          <p className="muted">{item.summary.logline}</p>
          <p className="muted mono">
            {formatDuration(item.duration_seconds)} · {plural(item.summary.segments, 'segment')}
          </p>
        </>
      ) : (
        <p className="muted">
          {item.min_seconds !== undefined && `${formatDuration(item.min_seconds)} to ${formatDuration(item.max_seconds)}`}
        </p>
      )}
      {item.error && <p className="muted">{item.error}</p>}
      <div className="row">
        <Button onClick={onGenerate} busy={busy || generating} variant={item.status === 'ready' ? 'secondary' : 'primary'}>
          {item.status === 'ready' ? 'Regenerate' : 'Generate'}
        </Button>
      </div>
    </Card>
  )
}
