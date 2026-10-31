import { useState } from 'react'

import { Badge, Button, Card, Empty, ErrorNote, Field, Loading, Notice, PageHeader } from '../../shared/ui'
import { plural } from '../../shared/lib/format'
import { useSeriesId } from '../series/api'
import { audioUrl, useCast, useCastActions } from './api'
import type { CastVoice, VoiceFields } from './types'

const NARRATOR = 'narrator'

function toForm(cast: CastVoice | null, suggestion: string): VoiceFields {
  return {
    voice: cast?.voice ?? suggestion,
    language: cast?.language ?? 'en',
    style: cast?.style ?? '',
    speed: cast?.speed ?? 1,
    consent_given: cast?.consent_given ?? false,
    consent_note: cast?.consent_note ?? '',
  }
}

export default function VoicesPage() {
  const seriesId = useSeriesId()
  const query = useCast(seriesId)
  const actions = useCastActions(seriesId)

  if (query.isPending) return <Loading />
  if (query.isError) return <div className="page"><ErrorNote error={query.error} onRetry={() => void query.refetch()} /></div>
  const { narrator, characters, uncast_speaking: uncast, without_consent: noConsent } = query.data

  return (
    <div className="page">
      <PageHeader
        title="Voices"
        subtitle="Pick a voice for each character and the narrator. Lines are spoken in these voices; samples need the job runner."
      />
      {uncast > 0 && <Notice tone="warn">{plural(uncast, 'speaking character')} without a cast voice use the look-sheet suggestion or the default.</Notice>}
      {noConsent > 0 && <Notice tone="warn">Record consent for the voice you chose for {plural(noConsent, 'character')}, especially for any cloned or real-person voice.</Notice>}
      {(actions.save.isError || actions.preview.isError) && <ErrorNote error={actions.save.error ?? actions.preview.error} />}
      <VoiceCard
        who={NARRATOR}
        title="Narrator"
        cast={narrator.cast}
        suggestion=""
        busy={actions.save.isPending || actions.preview.isPending}
        onSave={(fields) => actions.save.mutate({ who: NARRATOR, fields })}
        onPreview={() => actions.preview.mutate({ who: NARRATOR })}
      />
      {characters.length === 0 && <Empty title="No characters yet">Characters appear here once the story is analysed.</Empty>}
      {characters.map((c) => (
        <VoiceCard
          key={`${c.character_id}:${c.cast?.voice ?? ''}:${c.cast?.consent_given ?? ''}`}
          who={c.character_id}
          title={c.name}
          detail={c.lines > 0 ? plural(c.lines, 'line') : 'no lines yet'}
          cast={c.cast}
          suggestion={c.suggested_voice}
          busy={actions.save.isPending || actions.preview.isPending}
          onSave={(fields) => actions.save.mutate({ who: c.character_id, fields })}
          onPreview={() => actions.preview.mutate({ who: c.character_id })}
        />
      ))}
    </div>
  )
}

function VoiceCard(props: {
  who: string
  title: string
  detail?: string
  cast: CastVoice | null
  suggestion: string
  busy: boolean
  onSave: (fields: VoiceFields) => void
  onPreview: () => void
}) {
  const { cast, suggestion } = props
  const [form, setForm] = useState<VoiceFields>(() => toForm(cast, suggestion))
  const set = <K extends keyof VoiceFields>(key: K, value: VoiceFields[K]) => setForm((f) => ({ ...f, [key]: value }))
  const preview = cast?.preview
  const making = preview && (preview.status === 'queued' || preview.status === 'running')

  return (
    <Card>
      <div className="row row-between">
        <h3>
          {props.title} {props.detail && <span className="muted">· {props.detail}</span>}
        </h3>
        {cast ? <Badge tone={cast.consent_given ? 'ok' : 'warn'}>{cast.consent_given ? 'Consent recorded' : 'No consent yet'}</Badge> : <Badge>Not cast</Badge>}
      </div>
      <Field label="Voice" hint="A provider voice id, or describe it: &quot;older man, low, tired&quot;.">
        <input value={form.voice} onChange={(e) => set('voice', e.target.value)} />
      </Field>
      {suggestion && form.voice !== suggestion && (
        <p className="muted">
          Look sheet suggests: {suggestion}{' '}
          <Button variant="ghost" onClick={() => set('voice', suggestion)}>Use it</Button>
        </p>
      )}
      <div className="row">
        <Field label="Language">
          <input value={form.language} onChange={(e) => set('language', e.target.value)} size={6} />
        </Field>
        <Field label="Speed">
          <input type="number" min={0.5} max={2} step={0.05} value={form.speed} onChange={(e) => set('speed', Number(e.target.value) || 1)} />
        </Field>
        <Field label="Default delivery" hint="For example calm, clipped, warm.">
          <input value={form.style} onChange={(e) => set('style', e.target.value)} />
        </Field>
      </div>
      <label className="row">
        <input type="checkbox" checked={form.consent_given} onChange={(e) => set('consent_given', e.target.checked)} />
        <span>Consent to use this voice is on record</span>
      </label>
      <Field label="Consent note" hint="Who agreed, or the licence of a stock voice.">
        <input value={form.consent_note} onChange={(e) => set('consent_note', e.target.value)} />
      </Field>
      <div className="row">
        <Button variant="primary" busy={props.busy} onClick={() => props.onSave(form)}>Save voice</Button>
        <Button disabled={!cast || props.busy} onClick={props.onPreview} title={cast ? undefined : 'Save the voice first'}>
          {making ? 'Making sample…' : 'Play a sample'}
        </Button>
        {preview?.url && <audio controls preload="none" src={audioUrl(preview.url)} />}
      </div>
      {preview?.status === 'failed' && <p className="muted">The sample failed: {preview.error}</p>}
    </Card>
  )
}
