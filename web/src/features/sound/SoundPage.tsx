import { useState } from 'react'

import { Badge, Button, Card, Empty, ErrorNote, Loading, Notice, PageHeader } from '../../shared/ui'
import { formatDuration, plural } from '../../shared/lib/format'
import { useBreakdownOverview } from '../breakdown/api'
import { useSeriesId } from '../series/api'
import { audioUrl, useSoundActions, useSoundBoard, useSubtitles } from './api'
import type { BoardScene, BoardShot, Cue, CueStatus, CueType, SoundBoard } from './types'

const TYPE_LABEL: Record<CueType, string> = { dialogue: 'Dialogue', narration: 'Narration', sfx: 'Effect', ambience: 'Ambience', music: 'Music' }
const STATUS_TONE: Record<CueStatus, 'ok' | 'warn' | 'bad' | 'accent' | 'neutral'> = {
  planned: 'neutral', queued: 'accent', blocked: 'neutral', running: 'accent', awaiting_input: 'warn', ready: 'ok', failed: 'bad', rejected: 'bad',
}
const secs = (n: number | null | undefined) => (n === null || n === undefined ? '–' : `${n.toFixed(1)}s`)

export default function SoundPage() {
  const seriesId = useSeriesId()
  const overview = useBreakdownOverview(seriesId)
  const [picked, setPicked] = useState<string | null>(null)

  if (overview.isPending) return <Loading />
  if (overview.isError) return <div className="page"><ErrorNote error={overview.error} onRetry={() => void overview.refetch()} /></div>
  const episodes = overview.data.filter((e) => e.scene_count > 0)
  const episodeId = picked ?? episodes[0]?.id ?? null

  return (
    <div className="page">
      <PageHeader
        title="Sound"
        subtitle="Dialogue, narration, effects, ambience and music for each episode, with subtitles. Needs the job runner."
        actions={
          episodes.length > 0 && (
            <select aria-label="Episode" value={episodeId ?? ''} onChange={(e) => setPicked(e.target.value)}>
              {episodes.map((e) => (
                <option key={e.id} value={e.id}>Episode {e.episode_number} · {e.title}</option>
              ))}
            </select>
          )
        }
      />
      {episodeId === null ? (
        <Empty title="No broken-down episodes">Break an episode down into scenes and shots first; sound is made from those.</Empty>
      ) : (
        <Board key={episodeId} episodeId={episodeId} />
      )}
    </div>
  )
}

function Board({ episodeId }: { episodeId: string }) {
  const query = useSoundBoard(episodeId)
  const actions = useSoundActions(episodeId)
  const [showSrt, setShowSrt] = useState(false)
  const subtitles = useSubtitles(episodeId, showSrt)

  if (query.isPending) return <Loading />
  if (query.isError) return <ErrorNote error={query.error} onRetry={() => void query.refetch()} />
  const board = query.data
  const total = Object.values(board.counts).reduce((a, b) => a + (b ?? 0), 0)
  const working = board.job?.status === 'queued' || board.job?.status === 'running'
  const errors = [actions.generate, actions.review, actions.approveAll, actions.applyFit, actions.subtitles].find((m) => m.isError)

  return (
    <div className="stack">
      {errors && <ErrorNote error={errors.error} />}
      {board.job?.status === 'failed' && board.job.error_summary && <Notice tone="bad">Sound generation failed: {board.job.error_summary}</Notice>}
      {board.warnings.map((w) => <Notice key={w} tone="warn">{w}</Notice>)}
      <Card>
        <div className="row row-between">
          <div className="row">
            <Button variant="primary" busy={actions.generate.isPending || working} onClick={() => actions.generate.mutate(false)}>
              {total === 0 ? 'Generate sound' : 'Generate missing sound'}
            </Button>
            {total > 0 && <Button variant="ghost" disabled={working} onClick={() => actions.generate.mutate(true)}>Redesign cues</Button>}
            <Button busy={actions.approveAll.isPending} disabled={(board.counts.ready ?? 0) === 0} onClick={() => actions.approveAll.mutate()}>Approve all ready</Button>
            <Button busy={actions.subtitles.isPending} disabled={total === 0} onClick={() => actions.subtitles.mutate()}>Build subtitles</Button>
          </div>
          <div className="row">
            {(Object.keys(board.counts) as CueStatus[]).map((s) => <Badge key={s} tone={STATUS_TONE[s]}>{board.counts[s]} {s.replace('_', ' ')}</Badge>)}
          </div>
        </div>
        {board.overflow_shots > 0 && (
          <Notice tone="warn">
            {plural(board.overflow_shots, 'shot')} too short for the speech in {board.overflow_shots === 1 ? 'it' : 'them'}.{' '}
            <Button variant="ghost" busy={actions.applyFit.isPending} onClick={() => actions.applyFit.mutate()}>Lengthen to fit</Button>
          </Notice>
        )}
      </Card>
      {total === 0 && !working && <Empty title="No sound yet">Generate sound to write the cue list and make every line, effect and music cue.</Empty>}
      {board.theme && <Card><h3>Series theme</h3><CueRow cue={board.theme} actions={actions} /></Card>}
      {board.scenes.map((scene) => <SceneCard key={scene.id} scene={scene} actions={actions} />)}
      <Card>
        <div className="row row-between">
          <h3>Subtitles</h3>
          <Button variant="ghost" onClick={() => setShowSrt((v) => !v)} aria-expanded={showSrt}>{showSrt ? 'Hide' : 'Preview'}</Button>
        </div>
        <SubtitleSummary board={board} />
        {showSrt && (subtitles.isPending ? <Loading /> : subtitles.data?.srt ? <pre className="mono" style={{ whiteSpace: 'pre-wrap', maxHeight: 320, overflow: 'auto' }}>{subtitles.data.srt}</pre> : <p className="muted">No subtitle file yet. Use Build subtitles.</p>)}
      </Card>
    </div>
  )
}

function SubtitleSummary({ board }: { board: SoundBoard }) {
  const s = board.subtitles
  if (!s.episode) return <p className="muted">Not built yet. Subtitles come from the dialogue and narration, timed to the measured audio.</p>
  return <p className="muted">Built: the episode file, {plural(s.scenes, 'scene file')} and {plural(s.shots, 'shot file')}. <a href={audioUrl(s.episode.url)}>Download episode .srt</a></p>
}

type Actions = ReturnType<typeof useSoundActions>

function SceneCard({ scene, actions }: { scene: BoardScene; actions: Actions }) {
  const [open, setOpen] = useState(true)
  const late = scene.shots.filter((s) => s.fit?.status === 'overflow').length
  return (
    <Card>
      <div className="row row-between">
        <h3>{scene.scene_number}. {scene.title ?? 'Scene'} <span className="muted">· {plural(scene.cues.length, 'sound')}</span></h3>
        <div className="row">
          {late > 0 && <Badge tone="warn">{plural(late, 'shot')} too short</Badge>}
          <Button variant="ghost" onClick={() => setOpen((v) => !v)} aria-expanded={open}>{open ? 'Hide' : 'Show'}</Button>
        </div>
      </div>
      {open && (
        <>
          <ol className="event-list">{scene.shots.map((shot) => <li key={shot.id}><ShotLine shot={shot} /></li>)}</ol>
          {scene.cues.length === 0 ? <p className="muted">No sound planned for this scene.</p> : scene.cues.map((cue) => <CueRow key={cue.id} cue={cue} actions={actions} />)}
        </>
      )}
    </Card>
  )
}

function ShotLine({ shot }: { shot: BoardShot }) {
  const fit = shot.fit
  return (
    <>
      {shot.description} <span className="muted mono">{formatDuration(shot.duration_seconds)}</span>{' '}
      {fit && fit.status === 'ok' && <Badge tone="ok">speech fits{fit.measured ? '' : ' (estimated)'}</Badge>}
      {fit && fit.status === 'overflow' && (
        <Badge tone="warn">speech {secs(fit.audio_seconds)} · needs {secs(fit.suggested_seconds)}{fit.measured ? '' : ' (estimated)'}</Badge>
      )}
    </>
  )
}

function CueRow({ cue, actions }: { cue: Cue; actions: Actions }) {
  const [rejecting, setRejecting] = useState(false)
  const [note, setNote] = useState('')
  const reviewing = actions.review.isPending && actions.review.variables?.cueId === cue.id
  const who = cue.cue_type === 'dialogue' || cue.cue_type === 'narration' ? cue.speaker : null
  return (
    <div className="beat">
      <div className="row row-between">
        <span>
          <Badge>{TYPE_LABEL[cue.cue_type]}</Badge>{' '}
          {who && <strong>{who}</strong>}
          {cue.delivery && <span className="muted"> ({cue.delivery})</span>}
          {who ? ': ' : ' '}
          {cue.text}
        </span>
        <span className="row">
          {cue.audio_duration !== null && <span className="muted mono">{secs(cue.audio_duration)}</span>}
          <Badge tone={STATUS_TONE[cue.status]}>{cue.status === 'ready' && cue.review_status === 'approved' ? 'approved' : cue.status.replace('_', ' ')}</Badge>
        </span>
      </div>
      {cue.error && <p className="muted">{cue.error}</p>}
      {cue.review_note && cue.status !== 'ready' && <p className="muted">Revision note: {cue.review_note}</p>}
      {cue.audio && (
        <div className="row">
          <audio controls preload="none" src={audioUrl(cue.audio.url)} />
          {cue.review_status !== 'approved' && (
            <Button busy={reviewing} onClick={() => actions.review.mutate({ cueId: cue.id, decision: 'approve' })}>Approve</Button>
          )}
          <Button variant="ghost" onClick={() => setRejecting((v) => !v)} aria-expanded={rejecting}>Reject…</Button>
        </div>
      )}
      {rejecting && (
        <div className="row">
          <input aria-label="What to change" placeholder="What should be different?" value={note} onChange={(e) => setNote(e.target.value)} />
          <Button variant="danger" busy={reviewing} onClick={() => { actions.review.mutate({ cueId: cue.id, decision: 'reject', note }); setRejecting(false); setNote('') }}>
            Reject and redo
          </Button>
        </div>
      )}
    </div>
  )
}
