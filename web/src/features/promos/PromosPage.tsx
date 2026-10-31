import { useState } from 'react'

import { formatDuration, plural } from '../../shared/lib/format'
import { Badge, Button, Card, Empty, ErrorNote, Field, Loading, Notice, PageHeader } from '../../shared/ui'
import { useSeriesId } from '../series/api'
import { fileUrl, usePromoActions, usePromos } from './api'
import './promos.css'
import type { Promo, PromoItem, PromoKind, PromoRender, PromoRenderKind } from './types'

type Actions = ReturnType<typeof usePromoActions>

const DEFAULT_SECONDS: Record<PromoKind, number> = { teaser: 20, trailer: 60 }

export default function PromosPage() {
  const seriesId = useSeriesId()
  const query = usePromos(seriesId)
  const actions = usePromoActions(seriesId)
  const error = Object.values(actions).find((m) => m.isError)?.error

  return (
    <div className="page">
      <PageHeader
        title="Teaser & trailer"
        subtitle="A short teaser (about 20 seconds) or trailer (about a minute) cut from the series. Shots are picked from the story without giving away the ending."
      />
      <CreateCard actions={actions} />
      {error !== undefined && <ErrorNote error={error} />}
      {query.isPending && <Loading />}
      {query.isError && <ErrorNote error={query.error} onRetry={() => void query.refetch()} />}
      {query.isSuccess && query.data.length === 0 && <Empty title="Nothing yet">Create a teaser or trailer above. The shots come from your broken-down episodes.</Empty>}
      {query.isSuccess && query.data.map((promo) => <PromoCard key={promo.id} promo={promo} actions={actions} />)}
    </div>
  )
}

function CreateCard({ actions }: { actions: Actions }) {
  const [kind, setKind] = useState<PromoKind>('teaser')
  const [seconds, setSeconds] = useState('')
  const [notes, setNotes] = useState('')
  return (
    <Card>
      <h3>New</h3>
      <div className="row promo-create">
        <Field label="Kind">
          <select className="input" value={kind} onChange={(e) => setKind(e.target.value as PromoKind)}>
            <option value="teaser">Teaser</option>
            <option value="trailer">Trailer</option>
          </select>
        </Field>
        <Field label="Length in seconds" hint={`Default ${DEFAULT_SECONDS[kind]}`}>
          <input className="input" type="number" min={3} max={600} value={seconds} onChange={(e) => setSeconds(e.target.value)} />
        </Field>
        <Field label="Idea (optional)" hint="Tone, what to show, what to hold back">
          <input className="input promo-notes" value={notes} onChange={(e) => setNotes(e.target.value)} />
        </Field>
        <Button
          variant="primary"
          busy={actions.create.isPending}
          onClick={() =>
            actions.create.mutate(
              { kind, target_duration_seconds: seconds ? Number(seconds) : undefined, notes: notes || undefined, plan: true },
              { onSuccess: () => { setSeconds(''); setNotes('') } },
            )
          }
        >
          Create and plan
        </Button>
      </div>
    </Card>
  )
}

function PromoCard({ promo, actions }: { promo: Promo; actions: Actions }) {
  const p = promo.progress
  const missing = p.shots - p.with_clip
  const working = p.working > 0
  const lastMissing = actions.generateMissing.variables === promo.id ? actions.generateMissing.data : undefined
  const move = (index: number, by: number) => {
    const ids = promo.items.map((i) => i.id)
    const target = index + by
    if (target < 0 || target >= ids.length) return
    ;[ids[index], ids[target]] = [ids[target], ids[index]]
    actions.reorder.mutate({ id: promo.id, itemIds: ids })
  }

  return (
    <Card>
      <div className="row row-between">
        <h3>
          {promo.title} <span className="muted">· {promo.kind}</span>
        </h3>
        <div className="row">
          <Badge tone={promo.within_target ? 'ok' : 'warn'}>
            {formatDuration(promo.seconds)} of {promo.target_duration_seconds}s
          </Badge>
          <Button variant="ghost" busy={actions.plan.isPending && actions.plan.variables === promo.id} onClick={() => actions.plan.mutate(promo.id)} title="Ask for a new shot list: replaces the current one">
            Plan again
          </Button>
          <Button variant="ghost" onClick={() => { if (window.confirm(`Delete "${promo.title}"?`)) actions.remove.mutate(promo.id) }}>
            Delete
          </Button>
        </div>
      </div>
      {(promo.hook || promo.music_mood) && (
        <p className="muted">
          {promo.hook && <>Hook: {promo.hook}. </>}
          {promo.music_mood && <>Music: {promo.music_mood}.</>}
        </p>
      )}
      {promo.notes && <p className="muted">{promo.notes}</p>}

      <ol className="promo-strip">
        {promo.items.map((item, index) => (
          <ItemCard key={item.id} promoId={promo.id} item={item} index={index} last={index === promo.items.length - 1} move={move} actions={actions} />
        ))}
      </ol>
      <div className="row promo-add">
        <Button variant="ghost" onClick={() => actions.addItem.mutate({ id: promo.id, item: { type: 'title_card', text: 'Title', seconds: 2.5 } })}>
          + Title card
        </Button>
        <Button variant="ghost" onClick={() => actions.addItem.mutate({ id: promo.id, item: { type: 'narration', text: 'Narration line' } })}>
          + Narration
        </Button>
      </div>

      <div className="row promo-progress">
        <Button variant="primary" busy={actions.generateMissing.isPending && actions.generateMissing.variables === promo.id} disabled={promo.items.length === 0} onClick={() => actions.generateMissing.mutate(promo.id)}>
          Generate missing
        </Button>
        <span className="muted mono">
          keyframes {p.with_keyframe}/{p.shots} · clips {p.with_clip}/{p.shots} ({p.approved_clips} approved) · narration {p.narration_ready}/{p.narration} · music{' '}
          {promo.music ? promo.music.status : 'not made'}
          {working ? ` · ${plural(p.working, 'item')} in progress…` : ''}
        </span>
      </div>
      {lastMissing && (
        <Notice tone={lastMissing.problems.length ? 'warn' : 'ok'}>
          Requested {plural(lastMissing.keyframes_requested, 'keyframe')}, {plural(lastMissing.clips_requested, 'clip')}, {plural(lastMissing.voice_lines_requested, 'voice line')}
          {lastMissing.music_requested ? ' and music' : ''}; reused {lastMissing.reused_keyframes} keyframes and {lastMissing.reused_clips} clips.
          {lastMissing.clips_waiting_on_keyframe > 0 && ` ${plural(lastMissing.clips_waiting_on_keyframe, 'clip')} wait for their keyframe to be approved: approve it, then press this again.`}
          {lastMissing.problems.map((m) => ` ${m}`)}
        </Notice>
      )}
      {missing > 0 && p.with_clip === 0 && <p className="muted">Without clips, the animatic shows keyframes timed to the cut.</p>}

      <div className="promo-renders">
        {(['animatic', 'draft', 'final'] as PromoRenderKind[]).map((kind) => (
          <RenderBox key={kind} promo={promo} kind={kind} render={promo.renders?.[kind]} actions={actions} />
        ))}
      </div>
    </Card>
  )
}

function ItemCard({ promoId, item, index, last, move, actions }: { promoId: string; item: PromoItem; index: number; last: boolean; move: (i: number, by: number) => void; actions: Actions }) {
  const change = (changes: Parameters<Actions['updateItem']['mutate']>[0]['changes']) => actions.updateItem.mutate({ id: promoId, itemId: item.id, changes })
  const [text, setText] = useState(item.text ?? '')
  const frame = item.keyframe?.asset

  return (
    <li className={`promo-item promo-${item.type}`}>
      <div className="promo-item-media">
        {item.type === 'shot' ? (
          frame ? <img src={fileUrl(frame.url)} alt={`Keyframe for shot ${item.shot?.shot_number}`} loading="lazy" /> : <div className="promo-empty muted">No keyframe</div>
        ) : (
          <div className="promo-empty">{item.type === 'title_card' ? 'Title' : 'Voice'}</div>
        )}
      </div>
      <div className="stack promo-item-body">
        {item.type === 'shot' && item.shot && (
          <>
            <strong className="mono">
              E{item.shot.episode_number} · S{item.shot.scene_number} · shot {item.shot.shot_number}
            </strong>
            <span className="muted promo-desc">{item.shot.description}</span>
            <label className="row">
              <span className="muted">Seconds</span>
              <input className="input promo-num" type="number" min={1} max={60} step={0.5} defaultValue={item.trim_seconds ?? 3} onBlur={(e) => Number(e.target.value) > 0 && Number(e.target.value) !== item.trim_seconds && change({ trim_seconds: Number(e.target.value) })} />
            </label>
            <div className="row">
              <Badge tone={item.clip?.status === 'succeeded' ? 'ok' : item.clip ? 'accent' : 'neutral'}>{item.clip ? `clip ${item.clip.status}` : 'no clip'}</Badge>
              {item.clip?.status === 'succeeded' && item.clip.review_status !== 'approved' && <Badge tone="warn">not approved</Badge>}
            </div>
          </>
        )}
        {item.type !== 'shot' && (
          <>
            <input
              className="input"
              value={text}
              aria-label={item.type === 'title_card' ? 'Title card text' : 'Narration line'}
              onChange={(e) => setText(e.target.value)}
              onBlur={() => text.trim() && text !== item.text && change({ text })}
            />
            <label className="row">
              <span className="muted">Seconds</span>
              <input className="input promo-num" type="number" min={0.5} max={30} step={0.5} defaultValue={item.seconds ?? 2} onBlur={(e) => Number(e.target.value) > 0 && Number(e.target.value) !== item.seconds && change({ seconds: Number(e.target.value) })} />
            </label>
            {item.type === 'narration' && <Badge tone={item.voice?.status === 'succeeded' ? 'ok' : item.voice ? 'accent' : 'neutral'}>{item.voice ? `voice ${item.voice.status}` : 'no voice yet'}</Badge>}
          </>
        )}
        {item.reason && <span className="muted promo-reason">{item.reason}</span>}
      </div>
      <div className="promo-item-tools">
        <Button variant="ghost" aria-label="Move earlier" disabled={index === 0} onClick={() => move(index, -1)}>←</Button>
        <Button variant="ghost" aria-label="Move later" disabled={last} onClick={() => move(index, 1)}>→</Button>
        <Button variant="ghost" aria-label="Remove" onClick={() => actions.removeItem.mutate({ id: promoId, itemId: item.id })}>✕</Button>
      </div>
    </li>
  )
}

const RENDER_COPY: Record<PromoRenderKind, { title: string; blurb: string }> = {
  animatic: { title: 'Animatic', blurb: 'Keyframes timed to the cut, with titles, narration and music.' },
  draft: { title: 'Draft', blurb: 'Clips where they exist, keyframes where they do not. Low-res.' },
  final: { title: 'Final', blurb: 'Needs an approved clip for every shot. 1080p.' },
}

function RenderBox({ promo, kind, render, actions }: { promo: Promo; kind: PromoRenderKind; render?: PromoRender; actions: Actions }) {
  const working = render?.status === 'queued' || render?.status === 'running'
  const blocked =
    kind === 'final' && promo.progress.approved_clips < promo.progress.shots
      ? `${promo.progress.shots - promo.progress.approved_clips} shots still need an approved clip`
      : promo.items.length === 0
        ? 'No shots yet'
        : null
  const copy = RENDER_COPY[kind]
  return (
    <div className="promo-render">
      <div className="row row-between">
        <strong>{copy.title}</strong>
        {render && <Badge tone={render.status === 'succeeded' ? 'ok' : render.status === 'failed' ? 'bad' : 'accent'}>{render.status}</Badge>}
      </div>
      <p className="muted">{copy.blurb}</p>
      {render?.status === 'succeeded' && render.asset && <video key={render.asset.url} className="promo-player" src={fileUrl(render.asset.url)} controls preload="metadata" />}
      {render?.status === 'failed' && render.error_summary && <Notice tone="bad">{render.error_summary}</Notice>}
      {render?.status === 'succeeded' && <p className="muted mono">{formatDuration(render.duration_seconds)}</p>}
      <div className="row">
        <Button variant="primary" busy={working || (actions.render.isPending && actions.render.variables?.kind === kind && actions.render.variables.id === promo.id)} disabled={blocked !== null} title={blocked ?? undefined} onClick={() => actions.render.mutate({ id: promo.id, kind })}>
          {render ? 'Build again' : 'Build'}
        </Button>
        {render?.download_url && (
          <a className="btn btn-secondary" href={fileUrl(render.download_url)}>
            Download
          </a>
        )}
      </div>
      {blocked && <p className="muted">{blocked}.</p>}
    </div>
  )
}
