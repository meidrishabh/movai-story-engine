import { useState } from 'react'

import { Badge, Button, Card, Empty, ErrorNote, Loading, Notice, PageHeader } from '../../shared/ui'
import { formatDuration, plural } from '../../shared/lib/format'
import { useSeriesId } from '../series/api'
import { useBreakdownOverview, useEpisodeBreakdown, useQueueBreakdown } from './api'
import type { EpisodeBreakdownStatus } from './types'

function statusOf(e: EpisodeBreakdownStatus): { label: string; tone: 'ok' | 'warn' | 'bad' | 'accent' | 'neutral' } {
  if (e.job_status === 'queued' || e.job_status === 'running') return { label: 'Working', tone: 'accent' }
  if (e.job_status === 'failed' && e.scene_count === 0) return { label: 'Failed', tone: 'bad' }
  if (e.scene_count === 0) return { label: 'Not started', tone: 'neutral' }
  if (e.breakdown_stale) return { label: 'Out of date', tone: 'warn' }
  return { label: 'Ready', tone: 'ok' }
}

export default function BreakdownPage() {
  const seriesId = useSeriesId()
  const overview = useBreakdownOverview(seriesId)
  const { all, one } = useQueueBreakdown(seriesId)

  if (overview.isPending) return <Loading />
  if (overview.isError) return <div className="page"><ErrorNote error={overview.error} onRetry={() => void overview.refetch()} /></div>

  const episodes = overview.data
  const todo = episodes.filter((e) => statusOf(e).label === 'Not started' || statusOf(e).label === 'Out of date' || statusOf(e).label === 'Failed')

  return (
    <div className="page">
      <PageHeader
        title="Episode breakdown"
        subtitle="Each approved episode is split into scenes and timed shots."
        actions={
          <Button variant="primary" busy={all.isPending} disabled={todo.length === 0} onClick={() => all.mutate()}>
            Break down {todo.length > 0 ? `${todo.length} ` : ''}pending
          </Button>
        }
      />
      {all.isError && <ErrorNote error={all.error} />}
      {one.isError && <ErrorNote error={one.error} />}
      {episodes.length === 0 && <Empty title="No episodes yet">Approve episode plans first; each approved plan becomes an episode.</Empty>}
      {episodes.map((episode) => (
        <EpisodeRow key={episode.id} episode={episode} busy={one.isPending} onRun={() => one.mutate(episode.id)} />
      ))}
    </div>
  )
}

function EpisodeRow({ episode, busy, onRun }: { episode: EpisodeBreakdownStatus; busy: boolean; onRun: () => void }) {
  const [open, setOpen] = useState(false)
  const status = statusOf(episode)
  const working = status.label === 'Working'
  return (
    <Card>
      <div className="row row-between">
        <h3>
          Episode {episode.episode_number} <span className="muted">· {episode.title}</span>
        </h3>
        <Badge tone={status.tone}>{status.label}</Badge>
      </div>
      {episode.scene_count > 0 && (
        <p className="muted mono">
          {plural(episode.scene_count, 'scene')} · shots {formatDuration(episode.shot_seconds)} of {formatDuration(episode.target_duration_seconds)} planned
        </p>
      )}
      {episode.breakdown_stale && episode.scene_count > 0 && (
        <Notice tone="warn">The story around this episode changed. Break it down again to match.</Notice>
      )}
      {episode.job_status === 'failed' && episode.job_error && <p className="muted">{episode.job_error}</p>}
      <div className="row">
        <Button busy={busy || working} onClick={onRun}>
          {episode.scene_count > 0 ? 'Break down again' : 'Break down'}
        </Button>
        {episode.scene_count > 0 && (
          <Button variant="ghost" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
            {open ? 'Hide scenes' : 'Show scenes'}
          </Button>
        )}
      </div>
      {open && <Scenes episodeId={episode.id} />}
    </Card>
  )
}

function Scenes({ episodeId }: { episodeId: string }) {
  const breakdown = useEpisodeBreakdown(episodeId)
  if (breakdown.isPending) return <Loading />
  if (breakdown.isError) return <ErrorNote error={breakdown.error} onRetry={() => void breakdown.refetch()} />
  return (
    <div className="stack">
      {breakdown.data.items.map((scene) => (
        <div className="beat" key={scene.id}>
          <strong>
            {scene.scene_number}. {scene.title}
          </strong>
          {scene.description && <p className="muted">{scene.description}</p>}
          {scene.dialogue && scene.dialogue.length > 0 && (
            <div className="scene-dialogue">
              {scene.dialogue.map((line, index) => (
                <p key={index}>
                  <strong>{line.character}</strong>
                  {line.delivery && <span className="muted"> ({line.delivery})</span>}: {line.line}
                </p>
              ))}
            </div>
          )}
          <ol className="event-list">
            {scene.shots.map((shot) => (
              <li key={shot.shot_number}>
                {shot.description} <span className="muted mono">{shot.camera ? `${shot.camera} · ` : ''}{formatDuration(shot.duration_seconds)}</span>
              </li>
            ))}
          </ol>
        </div>
      ))}
    </div>
  )
}
