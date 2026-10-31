import { useState } from 'react'
import { NavLink, useParams } from 'react-router-dom'

import { Badge, Button, Card, Empty, ErrorNote, Field, Loading, Notice, PageHeader } from '../../shared/ui'
import { formatDuration, plural } from '../../shared/lib/format'
import { useBreakdownOverview } from '../breakdown/api'
import { useSeriesId } from '../series/api'
import { fileUrl, useVideoActions, useVideoBoard } from './api'
import type { Budget, ClipView, RenderKind, RenderView, ShotRow, TrimState, VideoBoard } from './types'
import './video.css'

export default function VideoPage() {
  const seriesId = useSeriesId()
  const { episodeId } = useParams()
  const overview = useBreakdownOverview(seriesId)

  if (overview.isPending) return <Loading />
  if (overview.isError) return <div className="page"><ErrorNote error={overview.error} onRetry={() => void overview.refetch()} /></div>
  const episodes = overview.data.filter((e) => e.scene_count > 0)

  return (
    <div className="page">
      <PageHeader title="Video" subtitle="Clips for each shot, a pacing check, and the assembled episode." />
      {episodes.length === 0 ? (
        <Empty title="No episodes to make video for">Break an episode down into scenes and shots first.</Empty>
      ) : (
        <nav className="video-tabs" aria-label="Episodes">
          {episodes.map((e) => (
            <NavLink key={e.id} to={`/series/${seriesId}/video/${e.id}`} className={({ isActive }) => `video-tab${isActive ? ' active' : ''}`}>
              Episode {e.episode_number}
            </NavLink>
          ))}
        </nav>
      )}
      {episodes.length > 0 && !episodeId && <Empty title="Pick an episode">Each episode has its own clips, budget and renders.</Empty>}
      {episodeId && <EpisodeBoard key={episodeId} episodeId={episodeId} />}
    </div>
  )
}

function EpisodeBoard({ episodeId }: { episodeId: string }) {
  const board = useVideoBoard(episodeId)
  const actions = useVideoActions(episodeId)
  if (board.isPending) return <Loading />
  if (board.isError) return <ErrorNote error={board.error} onRetry={() => void board.refetch()} />
  const data = board.data
  const errors = [actions.plan, actions.review, actions.holdLastFrame, actions.budget, actions.pause, actions.render].filter((m) => m.isError)

  const scenes = new Map<string, { title: string; number: number; shots: ShotRow[] }>()
  for (const shot of data.shots) {
    const scene = scenes.get(shot.scene_id) ?? { title: shot.scene_title, number: shot.scene_number, shots: [] }
    scene.shots.push(shot)
    scenes.set(shot.scene_id, scene)
  }

  return (
    <div className="stack">
      <h2>
        Episode {data.episode.episode_number} <span className="muted">· {data.episode.title}</span>
      </h2>
      {errors.map((m, i) => (
        <ErrorNote key={i} error={m.error} />
      ))}
      <Summary data={data} />
      <BudgetPanel data={data} actions={actions} />
      <div className="video-renders">
        {(['animatic', 'draft', 'final'] as RenderKind[]).map((kind) => (
          <RenderCard key={kind} kind={kind} data={data} busy={actions.render.isPending} onBuild={() => actions.render.mutate(kind)} />
        ))}
      </div>
      {[...scenes.entries()].map(([sceneId, scene]) => (
        <Card key={sceneId}>
          <h3>
            Scene {scene.number} <span className="muted">· {scene.title}</span>
          </h3>
          <div className="stack">
            {scene.shots.map((shot) => (
              <ShotCard key={shot.shot_id} shot={shot} budget={data.budget} actions={actions} />
            ))}
          </div>
        </Card>
      ))}
    </div>
  )
}

function Summary({ data }: { data: VideoBoard }) {
  const s = data.summary
  const tile = (label: string, value: number | string, tone?: string) => (
    <div className="tile">
      <span className="muted">{label}</span>
      <span className={`tile-value ${tone ?? ''}`}>{value}</span>
    </div>
  )
  return (
    <div className="tiles">
      {tile('Shots', s.shots)}
      {tile('With keyframe', `${s.with_keyframe}/${s.shots}`)}
      {tile('Clips approved', `${s.approved}/${s.shots}`)}
      {tile('Waiting for review', s.pending_review)}
      {tile('Needs attention', s.attention + s.failed, s.attention + s.failed > 0 ? 'text-bad' : undefined)}
    </div>
  )
}

function BudgetPanel({ data, actions }: { data: VideoBoard; actions: ReturnType<typeof useVideoActions> }) {
  const b: Budget = data.budget
  const [retries, setRetries] = useState(String(b.max_retries_per_shot))
  const [cap, setCap] = useState(b.max_cost === null ? '' : String(b.max_cost))
  const missing = data.shots.filter((s) => !s.clip).length
  const readyForClip = data.shots.filter((s) => !s.clip && s.keyframe?.review_status === 'approved').length
  const lastPlan = actions.plan.data
  return (
    <Card>
      <div className="row row-between">
        <h3>Clips and budget</h3>
        <div className="row">
          {b.paused && <Badge tone="warn">Paused</Badge>}
          {b.over_cost && <Badge tone="bad">Over cost cap</Badge>}
        </div>
      </div>
      <p className="muted mono">
        Spent {b.cost_total.toFixed(2)}
        {b.max_cost !== null ? ` of ${b.max_cost}` : ' (no cap)'} · up to {b.max_retries_per_shot} regenerations per shot
      </p>
      <div className="row video-budget">
        <Button
          variant="primary"
          busy={actions.plan.isPending}
          disabled={readyForClip === 0}
          onClick={() => actions.plan.mutate({})}
          title={readyForClip === 0 ? 'Shots need an approved keyframe first' : undefined}
        >
          Make {readyForClip > 0 ? plural(readyForClip, 'clip') : 'clips'}
        </Button>
        <Button busy={actions.pause.isPending} onClick={() => actions.pause.mutate(!b.paused)}>
          {b.paused ? 'Resume' : 'Pause'}
        </Button>
        <Field label="Regenerations per shot">
          <input className="input" type="number" min={0} max={50} value={retries} onChange={(e) => setRetries(e.target.value)} />
        </Field>
        <Field label="Cost cap" hint="Empty for none">
          <input className="input" type="number" min={0} step="0.01" value={cap} onChange={(e) => setCap(e.target.value)} />
        </Field>
        <Button
          busy={actions.budget.isPending}
          onClick={() => actions.budget.mutate({ max_retries_per_shot: Number(retries) || 0, max_cost: cap === '' ? null : Number(cap) })}
        >
          Save limits
        </Button>
      </div>
      {missing > readyForClip && (
        <p className="muted">{plural(missing - readyForClip, 'shot')} still need an approved keyframe before a clip can be made.</p>
      )}
      {lastPlan && <Notice>{lastPlan.created === 0 ? 'No new clips were needed.' : `${plural(lastPlan.created, 'clip')} queued.`}</Notice>}
    </Card>
  )
}

const RENDER_COPY: Record<RenderKind, { title: string; blurb: string }> = {
  animatic: { title: 'Animatic', blurb: 'Keyframes timed to the shot lengths: check pacing before paying for video.' },
  draft: { title: 'Draft episode', blurb: 'The clips trimmed and stitched, low-res. A shot without a clip shows its keyframe.' },
  final: { title: 'Final export', blurb: 'Needs an approved clip for every shot. Stitched, then upscaled to 1080p.' },
}

function RenderCard({ kind, data, busy, onBuild }: { kind: RenderKind; data: VideoBoard; busy: boolean; onBuild: () => void }) {
  const render: RenderView | undefined = data.renders[kind]
  const [sceneAsset, setSceneAsset] = useState<string | null>(null)
  const copy = RENDER_COPY[kind]
  const working = render?.status === 'queued' || render?.status === 'running'
  const blocked =
    kind === 'final' && data.summary.approved < data.summary.shots
      ? `${data.summary.shots - data.summary.approved} shots still need an approved clip`
      : kind === 'animatic' && data.summary.with_keyframe === 0
        ? 'No keyframes yet'
        : kind === 'draft' && data.summary.approved + data.summary.pending_review === 0
          ? 'No finished clips yet'
          : null
  const src = sceneAsset ? fileUrl(`/api/v1/assets/${sceneAsset}/file`) : render?.asset ? fileUrl(render.asset.url) : null
  return (
    <Card>
      <div className="row row-between">
        <h3>{copy.title}</h3>
        {render && <Badge tone={render.status === 'succeeded' ? 'ok' : render.status === 'failed' ? 'bad' : 'accent'}>{render.status}</Badge>}
      </div>
      <p className="muted">{copy.blurb}</p>
      {src && render?.status === 'succeeded' && <video key={src} className="video-player" src={src} controls preload="metadata" />}
      {render?.status === 'failed' && render.error_summary && <Notice tone="bad">{render.error_summary}</Notice>}
      {render?.status === 'succeeded' && (
        <p className="muted mono">
          {formatDuration(render.duration_seconds)} · {render.details.profile?.width}×{render.details.profile?.height}
          {render.details.unchanged ? ' · nothing changed since the last build' : ''}
          {render.details.stills && render.details.stills.length > 0 ? ` · ${plural(render.details.stills.length, 'shot')} shown as keyframe` : ''}
        </p>
      )}
      {render?.details.scenes && render.details.scenes.length > 1 && render.status === 'succeeded' && (
        <div className="row video-scenes">
          <Button variant={sceneAsset ? 'ghost' : 'secondary'} onClick={() => setSceneAsset(null)}>
            Whole episode
          </Button>
          {render.details.scenes.map((s) => (
            <Button key={s.scene_id} variant={sceneAsset === s.asset_id ? 'secondary' : 'ghost'} onClick={() => setSceneAsset(s.asset_id)}>
              Scene {s.scene_number}
            </Button>
          ))}
        </div>
      )}
      <div className="row">
        <Button variant="primary" busy={busy || working} disabled={blocked !== null} onClick={onBuild} title={blocked ?? undefined}>
          {render ? 'Build again' : 'Build'}
        </Button>
        {render?.download_url && (
          <a className="btn btn-secondary" href={fileUrl(render.download_url)}>
            Download
          </a>
        )}
      </div>
      {blocked && <p className="muted">{blocked}.</p>}
    </Card>
  )
}

const TRIM_TEXT: Record<TrimState, { label: string; tone: 'ok' | 'warn' | 'bad' | 'neutral' }> = {
  exact: { label: 'Right length', tone: 'ok' },
  trim: { label: 'Will be trimmed', tone: 'neutral' },
  short: { label: 'Too short', tone: 'bad' },
  hold: { label: 'Last frame held', tone: 'warn' },
  unknown: { label: 'Length unknown', tone: 'neutral' },
  unplayable: { label: 'Not a playable video', tone: 'bad' },
}

function ShotCard({ shot, budget, actions }: { shot: ShotRow; budget: Budget; actions: ReturnType<typeof useVideoActions> }) {
  const clip = shot.clip
  return (
    <div className="beat video-shot">
      <div className="video-shot-media">
        {shot.keyframe?.asset ? (
          <img className="video-thumb" src={fileUrl(shot.keyframe.asset.url)} alt={`Keyframe for shot ${shot.shot_number}`} loading="lazy" />
        ) : (
          <div className="video-thumb video-thumb-empty muted">No keyframe</div>
        )}
        {clip?.asset && clip.status === 'succeeded' && clip.trim !== 'unplayable' ? (
          <video
            className="video-thumb"
            src={fileUrl(clip.asset.url)}
            poster={shot.keyframe?.asset ? fileUrl(shot.keyframe.asset.url) : undefined}
            controls
            preload="none"
          />
        ) : (
          <div className="video-thumb video-thumb-empty muted">{clip ? clipStatusText(clip) : 'No clip yet'}</div>
        )}
      </div>
      <div className="stack video-shot-body">
        <div className="row row-between">
          <strong>
            Shot {shot.shot_number}
            <span className="muted mono"> · {shot.camera ? `${shot.camera} · ` : ''}{shot.duration_seconds}s</span>
          </strong>
          {clip && <ClipBadges clip={clip} />}
        </div>
        <p>{shot.description}</p>
        {clip && <ClipControls clip={clip} budget={budget} actions={actions} />}
      </div>
    </div>
  )
}

function clipStatusText(clip: ClipView): string {
  if (clip.held_reason) return clip.held_reason === 'paused' ? 'Paused' : 'Over cost cap'
  if (clip.status === 'failed') return 'Failed'
  if (clip.status === 'blocked') return 'Waiting'
  if (clip.status === 'rejected') return 'Rejected'
  return 'Making…'
}

function ClipBadges({ clip }: { clip: ClipView }) {
  if (clip.status !== 'succeeded') {
    return <Badge tone={clip.status === 'failed' ? 'bad' : clip.held_reason ? 'warn' : 'accent'}>{clipStatusText(clip)}</Badge>
  }
  const trim = TRIM_TEXT[clip.trim]
  return (
    <div className="row">
      <Badge tone={trim.tone}>
        {trim.label}
        {clip.actual_seconds !== null && clip.trim !== 'exact' ? ` · ${clip.actual_seconds}s of ${clip.needed_seconds}s` : ''}
      </Badge>
      <Badge tone={clip.review_status === 'approved' ? 'ok' : 'neutral'}>{clip.review_status === 'approved' ? 'Approved' : 'Not reviewed'}</Badge>
    </div>
  )
}

function ClipControls({ clip, budget, actions }: { clip: ClipView; budget: Budget; actions: ReturnType<typeof useVideoActions> }) {
  const [rejecting, setRejecting] = useState(false)
  const [note, setNote] = useState('')
  if (clip.status === 'failed') {
    return clip.error_summary ? <p className="muted">{clip.error_summary}</p> : null
  }
  if (clip.status !== 'succeeded') return null
  const approved = clip.review_status === 'approved'
  const attemptsLeft = budget.max_retries_per_shot + 1 - clip.attempts
  return (
    <div className="stack">
      {clip.review_note && <p className="muted">Last note: {clip.review_note}</p>}
      <div className="row">
        {!approved && (
          <Button variant="primary" busy={actions.review.isPending} onClick={() => actions.review.mutate({ requestId: clip.request_id, decision: 'approve' })}>
            Approve
          </Button>
        )}
        {clip.trim === 'short' && (
          <Button onClick={() => actions.holdLastFrame.mutate({ requestId: clip.request_id, hold: true })}>Hold last frame</Button>
        )}
        {clip.trim === 'hold' && (
          <Button variant="ghost" onClick={() => actions.holdLastFrame.mutate({ requestId: clip.request_id, hold: false })}>
            Stop holding last frame
          </Button>
        )}
        <Button variant="ghost" disabled={attemptsLeft <= 0} onClick={() => setRejecting((v) => !v)} title={attemptsLeft <= 0 ? 'Regeneration limit reached' : undefined}>
          Regenerate…
        </Button>
        <span className="muted mono">
          attempt {clip.attempts} · {attemptsLeft > 0 ? `${attemptsLeft} left` : 'none left'}
        </span>
      </div>
      {rejecting && (
        <div className="row">
          <input className="input video-note" placeholder="What should change? (optional)" value={note} onChange={(e) => setNote(e.target.value)} />
          <Button
            variant="danger"
            busy={actions.review.isPending}
            onClick={() => {
              actions.review.mutate({ requestId: clip.request_id, decision: 'reject', note })
              setRejecting(false)
              setNote('')
            }}
          >
            Reject and regenerate
          </Button>
        </div>
      )}
    </div>
  )
}
