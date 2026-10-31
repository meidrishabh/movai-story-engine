import { useState } from 'react'
import { Link } from 'react-router-dom'

import { formatDuration, plural } from '../../shared/lib/format'
import { Badge, Button, Card, Empty, ErrorNote, Loading, Notice, PageHeader } from '../../shared/ui'
import { useSeriesId } from '../series/api'
import { assetUrl, useEpisodeKeyframes, useKeyframeActions, useKeyframeOverview } from './api'
import './keyframes.css'
import type { Keyframe, KeyframeShot } from './types'

type Tone = 'ok' | 'warn' | 'bad' | 'accent' | 'neutral'
type Filter = 'all' | 'review' | 'working' | 'failed' | 'missing' | 'flagged'

const FILTERS: { id: Filter; label: string }[] = [
  { id: 'all', label: 'All' },
  { id: 'review', label: 'Needs review' },
  { id: 'working', label: 'Working' },
  { id: 'failed', label: 'Failed' },
  { id: 'missing', label: 'Not generated' },
  { id: 'flagged', label: 'Check flagged' },
]

function describe(k: Keyframe | null): { label: string; tone: Tone; hint: string } {
  if (!k) return { label: 'Not generated', tone: 'neutral', hint: 'No keyframe yet' }
  switch (k.status) {
    case 'queued':
      return { label: 'Queued', tone: 'accent', hint: 'Waiting for the job runner' }
    case 'running':
      return { label: 'Generating', tone: 'accent', hint: 'Generating…' }
    case 'blocked':
      return { label: 'Waiting', tone: 'warn', hint: 'Waiting for a reference image to be approved' }
    case 'awaiting_input':
      return { label: 'Waiting for upload', tone: 'warn', hint: 'Waiting for the image to be supplied' }
    case 'failed':
      return { label: 'Failed', tone: 'bad', hint: k.error_summary ?? 'Generation failed' }
    case 'rejected':
      return { label: 'Rejected', tone: 'bad', hint: 'Rejected' }
    default:
      return k.review_status === 'approved'
        ? { label: 'Approved', tone: 'ok', hint: '' }
        : { label: 'Needs review', tone: 'warn', hint: '' }
  }
}

function matches(filter: Filter, k: Keyframe | null): boolean {
  if (filter === 'all') return true
  if (filter === 'missing') return k === null
  if (!k) return false
  if (filter === 'review') return k.status === 'succeeded' && k.review_status === 'pending'
  if (filter === 'working') return ['queued', 'running', 'blocked', 'awaiting_input'].includes(k.status)
  if (filter === 'failed') return k.status === 'failed'
  return k.checks.status === 'flagged'
}

export default function KeyframesPage() {
  const seriesId = useSeriesId()
  const overview = useKeyframeOverview(seriesId)
  const [picked, setPicked] = useState<string | null>(null)

  if (overview.isPending) return <Loading />
  if (overview.isError) return <div className="page"><ErrorNote error={overview.error} onRetry={() => void overview.refetch()} /></div>

  const episodes = overview.data.items
  const episodeId = picked && episodes.some((e) => e.id === picked) ? picked : episodes[0]?.id

  return (
    <div className="page">
      <PageHeader
        title="Keyframes"
        subtitle="One still image per shot. Each is the first frame its video clip is animated from, so review them before any video is made."
      />
      {!overview.data.style_approved && (
        <Notice tone="warn">
          The style bible is not approved yet, so keyframes cannot be made. <Link to="../style">Open the style bible</Link>.
        </Notice>
      )}
      {episodes.length === 0 ? (
        <Empty title="No shots yet">Break an episode down into scenes and shots first; each shot gets a keyframe.</Empty>
      ) : (
        <>
          <div className="kf-tabs" role="group" aria-label="Episode">
            {episodes.map((e) => (
              <button key={e.id} className="kf-tab" aria-pressed={e.id === episodeId} onClick={() => setPicked(e.id)}>
                <strong>Episode {e.episode_number}</strong>
                <small>
                  {e.approved}/{e.shots} approved{e.needs_review > 0 ? ` · ${e.needs_review} to review` : ''}
                  {e.working > 0 ? ` · ${e.working} working` : ''}
                </small>
              </button>
            ))}
          </div>
          {episodeId && <EpisodeView key={episodeId} seriesId={seriesId} episodeId={episodeId} styleApproved={overview.data.style_approved} />}
        </>
      )}
    </div>
  )
}

function EpisodeView({ seriesId, episodeId, styleApproved }: { seriesId: string; episodeId: string; styleApproved: boolean }) {
  const grid = useEpisodeKeyframes(episodeId)
  const actions = useKeyframeActions(seriesId, episodeId)
  const [filter, setFilter] = useState<Filter>('all')

  if (grid.isPending) return <Loading />
  if (grid.isError) return <ErrorNote error={grid.error} onRetry={() => void grid.refetch()} />

  const { totals, scenes, episode } = grid.data
  const missing = totals.not_generated + totals.failed
  const counts: Record<Filter, number> = {
    all: totals.shots,
    review: totals.needs_review,
    working: totals.working,
    failed: totals.failed,
    missing: totals.not_generated,
    flagged: totals.flagged,
  }

  return (
    <>
      <div className="row row-between">
        <h3>
          Episode {episode.episode_number} <span className="muted">· {episode.title}</span>
        </h3>
        <Button
          variant="primary"
          busy={actions.generate.isPending}
          disabled={!styleApproved || missing === 0}
          onClick={() => actions.generate.mutate(false)}
        >
          Generate {missing > 0 ? `${plural(missing, 'missing keyframe')}` : 'keyframes'}
        </Button>
      </div>
      {actions.generate.isError && <ErrorNote error={actions.generate.error} />}
      {actions.generate.isSuccess && actions.generate.data.created > 0 && (
        <Notice tone="ok">
          Queued {plural(actions.generate.data.created, 'keyframe')} in story order. The job runner makes them one by one.
        </Notice>
      )}
      <div className="row">
        {FILTERS.map((f) => (
          <Button key={f.id} variant={filter === f.id ? 'primary' : 'ghost'} onClick={() => setFilter(f.id)}>
            {f.label} {counts[f.id]}
          </Button>
        ))}
      </div>
      {actions.review.isError && <ErrorNote error={actions.review.error} />}
      {actions.regenerate.isError && <ErrorNote error={actions.regenerate.error} />}
      {scenes.map((scene) => {
        const shots = scene.shots.filter((s) => matches(filter, s.keyframe))
        if (shots.length === 0) return null
        return (
          <section className="kf-scene" key={scene.id}>
            <div>
              <strong>
                Scene {scene.scene_number}
                {scene.title ? `: ${scene.title}` : ''}
              </strong>
              <span className="muted">
                {' '}
                {[scene.location, scene.time_of_day].filter(Boolean).join(' · ')}
              </span>
            </div>
            <div className="kf-grid">
              {shots.map((shot) => (
                <ShotCard key={shot.id} shot={shot} actions={actions} />
              ))}
            </div>
          </section>
        )
      })}
    </>
  )
}

type Actions = ReturnType<typeof useKeyframeActions>

function ShotCard({ shot, actions }: { shot: KeyframeShot; actions: Actions }) {
  const k = shot.keyframe
  const state = describe(k)
  const [open, setOpen] = useState(false)
  const [rejecting, setRejecting] = useState(false)
  const [note, setNote] = useState('')
  const reviewable = k?.status === 'succeeded' && k.review_status === 'pending'
  const flagged = k?.checks.status === 'flagged'

  return (
    <Card className="kf-card">
      <div className="kf-thumb">
        {k?.result ? (
          <img src={assetUrl(k.result.id)} alt={`Keyframe for shot ${shot.shot_number}`} loading="lazy" />
        ) : (
          <span>{state.hint}</span>
        )}
      </div>
      <div className="kf-meta">
        <strong className="mono">Shot {shot.shot_number}</strong>
        <Badge tone={state.tone}>{state.label}</Badge>
        {flagged && <Badge tone="bad">Check flagged</Badge>}
        {k && k.attempts > 1 && <span className="muted mono">attempt {k.attempts}</span>}
        <span className="muted mono">
          {shot.camera ? `${shot.camera} · ` : ''}
          {formatDuration(shot.duration_seconds)}
        </span>
      </div>
      <p>{shot.description}</p>
      {shot.characters.length > 0 && <p className="muted">{shot.characters.join(', ')}</p>}
      {k?.review_status === 'rejected' && k.review_note && <p className="muted">Rejected: {k.review_note}</p>}
      {k?.status === 'failed' && k.error_summary && <Notice tone="bad">{k.error_summary}</Notice>}
      {k && k.warnings.length > 0 && (
        <Notice tone="warn">
          {k.warnings.slice(0, 3).join(' · ')}
          {k.warnings.length > 3 ? ` · and ${k.warnings.length - 3} more` : ''}
        </Notice>
      )}

      <div className="row">
        {reviewable && (
          <>
            <Button
              variant="primary"
              busy={actions.review.isPending}
              onClick={() => actions.review.mutate({ requestId: k.id, decision: 'approve' })}
            >
              Approve
            </Button>
            <Button variant="danger" onClick={() => setRejecting((v) => !v)} aria-expanded={rejecting}>
              Reject…
            </Button>
          </>
        )}
        {k?.status === 'failed' && (
          <Button busy={actions.retry.isPending} onClick={() => actions.retry.mutate(k.id)}>
            Retry
          </Button>
        )}
        {(!k || k.status === 'succeeded' || k.status === 'failed') && (
          <Button variant={k ? 'ghost' : 'secondary'} busy={actions.regenerate.isPending} onClick={() => actions.regenerate.mutate(shot.id)}>
            {k ? 'Regenerate' : 'Generate'}
          </Button>
        )}
        {k && (
          <Button variant="ghost" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
            {open ? 'Hide prompt' : 'Prompt & references'}
          </Button>
        )}
      </div>

      {rejecting && reviewable && (
        <div className="stack">
          <label className="field-hint" htmlFor={`note-${k.id}`}>
            What should change? The note is added to the prompt for the next attempt.
          </label>
          <input
            id={`note-${k.id}`}
            className="kf-note"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="For example: make the room darker, face older"
          />
          <div className="row">
            <Button
              variant="danger"
              busy={actions.review.isPending}
              onClick={() =>
                actions.review.mutate(
                  { requestId: k.id, decision: 'reject', note: note.trim() || undefined },
                  { onSuccess: () => { setRejecting(false); setNote('') } },
                )
              }
            >
              Reject and regenerate
            </Button>
            <Button variant="ghost" onClick={() => setRejecting(false)}>
              Cancel
            </Button>
          </div>
        </div>
      )}

      {open && k && <PromptDetail keyframe={k} actions={actions} />}
    </Card>
  )
}

function PromptDetail({ keyframe: k, actions }: { keyframe: Keyframe; actions: Actions }) {
  const [copied, setCopied] = useState<string | null>(null)

  async function copy(label: string, value: string) {
    try {
      await navigator.clipboard.writeText(value)
      setCopied(label)
      window.setTimeout(() => setCopied(null), 1500)
    } catch {
      setCopied(null) // clipboard blocked: the text is selectable in the box
    }
  }

  return (
    <div className="kf-detail">
      <div className="row row-between">
        <strong>Prompt</strong>
        <Button variant="secondary" onClick={() => void copy('prompt', k.prompt)}>
          {copied === 'prompt' ? 'Copied' : 'Copy prompt'}
        </Button>
      </div>
      <textarea className="kf-prompt" readOnly value={k.prompt} aria-label="Exact prompt sent for this keyframe" />
      {k.negative_prompt && (
        <>
          <div className="row row-between">
            <strong>Negative prompt</strong>
            <Button variant="ghost" onClick={() => void copy('negative', k.negative_prompt ?? '')}>
              {copied === 'negative' ? 'Copied' : 'Copy'}
            </Button>
          </div>
          <p className="muted mono">{k.negative_prompt}</p>
        </>
      )}
      <strong>References attached</strong>
      {k.references.length === 0 ? (
        <p className="muted">None. The prompt text alone defines this image.</p>
      ) : (
        <div className="kf-refs">
          {k.references.map((r) => (
            <div className="kf-ref" key={r.asset_id}>
              <img src={assetUrl(r.asset_id)} alt={r.label} loading="lazy" />
              <span>{r.label}</span>
            </div>
          ))}
        </div>
      )}
      <div className="row row-between">
        <span className="muted">
          Consistency check:{' '}
          {k.checks.status ? `${k.checks.status}${k.checks.score != null ? ` (${k.checks.score.toFixed(2)})` : ''}` : 'not run'}
          {k.checks.notes ? ` · ${k.checks.notes}` : ''}
        </span>
        {k.status === 'succeeded' && (
          <Button variant="ghost" busy={actions.check.isPending} onClick={() => actions.check.mutate(k.id)}>
            Run check
          </Button>
        )}
      </div>
    </div>
  )
}
