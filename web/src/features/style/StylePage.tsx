import { useState } from 'react'

import { Badge, Button, Card, Empty, ErrorNote, Field, Loading, Notice, PageHeader } from '../../shared/ui'
import { useSeriesId } from '../series/api'
import { useStyleActions, useStyleBible } from './api'
import type { StyleBible, StyleFields, StyleOverride } from './types'

type TextKey = Exclude<keyof StyleFields, 'per_act_overrides'>

const TEXT_FIELDS: { key: TextKey; label: string; hint: string; rows: number }[] = [
  { key: 'theme_tone', label: 'Theme and tone', hint: 'The mood the look has to support.', rows: 2 },
  { key: 'medium', label: 'Medium', hint: 'One choice, for example "2D hand-drawn animation" or "cel-shaded anime".', rows: 1 },
  { key: 'art_style', label: 'Art style', hint: 'Line quality, texture, level of detail, reference looks.', rows: 3 },
  { key: 'palette', label: 'Palette', hint: 'Main colours, one accent, and the overall grade.', rows: 2 },
  { key: 'lighting', label: 'Lighting', hint: 'For example "hard single-source light, deep shadows".', rows: 2 },
  { key: 'camera_language', label: 'Camera', hint: 'Lens and framing habits.', rows: 2 },
  { key: 'negative_style', label: 'Avoid', hint: 'What every image must not contain.', rows: 2 },
]

function toForm(bible: StyleBible): StyleFields {
  return {
    theme_tone: bible.theme_tone ?? '',
    medium: bible.medium ?? '',
    art_style: bible.art_style ?? '',
    palette: bible.palette ?? '',
    lighting: bible.lighting ?? '',
    camera_language: bible.camera_language ?? '',
    negative_style: bible.negative_style ?? '',
    per_act_overrides: bible.per_act_overrides.map((o) => ({ when: o.when ?? '', change: o.change ?? '' })),
  }
}

export default function StylePage() {
  const seriesId = useSeriesId()
  const query = useStyleBible(seriesId)
  const { generate, save, approve } = useStyleActions(seriesId)

  if (query.isPending) return <Loading />
  if (query.isError) return <div className="page"><ErrorNote error={query.error} onRetry={() => void query.refetch()} /></div>

  const { bible, approved, style_block: block } = query.data

  return (
    <div className="page">
      <PageHeader
        title="Style bible"
        subtitle="One look for the whole series. Every image and clip is made from this, so the film looks consistent."
        actions={
          bible && (
            <Badge tone={approved ? 'ok' : 'warn'}>
              {approved ? `Approved · v${bible.version}` : `Draft · v${bible.version}`}
            </Badge>
          )
        }
      />
      {generate.isError && <ErrorNote error={generate.error} />}
      {!bible ? (
        <Empty title="No style yet">
          <p>The style is drafted from your story: its genre, mood, places and characters. You can edit every part before approving it.</p>
          <Button variant="primary" busy={generate.isPending} onClick={() => generate.mutate(false)}>
            Write a style from the story
          </Button>
        </Empty>
      ) : (
        // Remounted when the server copy changes, so the form always starts from what was saved.
        <StyleEditor
          key={`${bible.id}-${bible.updated_at}`}
          bible={bible}
          block={block}
          saving={save.isPending}
          approving={approve.isPending}
          generating={generate.isPending}
          error={save.isError ? save.error : approve.isError ? approve.error : null}
          onSave={(fields) => save.mutate(fields)}
          onApprove={() => approve.mutate()}
          onRegenerate={() => generate.mutate(approved)}
        />
      )}
    </div>
  )
}

interface EditorProps {
  bible: StyleBible
  block: string | null
  saving: boolean
  approving: boolean
  generating: boolean
  error: unknown
  onSave: (fields: StyleFields) => void
  onApprove: () => void
  onRegenerate: () => void
}

function StyleEditor({ bible, block, saving, approving, generating, error, onSave, onApprove, onRegenerate }: EditorProps) {
  const original = toForm(bible)
  const [form, setForm] = useState<StyleFields>(original)
  const [confirmRegenerate, setConfirmRegenerate] = useState(false)
  const approved = bible.status === 'approved'
  const dirty = JSON.stringify(form) !== JSON.stringify(original)

  const setOverride = (index: number, patch: Partial<StyleOverride>) =>
    setForm({ ...form, per_act_overrides: form.per_act_overrides.map((o, i) => (i === index ? { ...o, ...patch } : o)) })

  return (
    <>
      {approved && !dirty && <Notice tone="ok">Approved. Editing it sends it back to draft until you approve it again.</Notice>}
      {error !== null && <ErrorNote error={error} />}
      <Card>
        <div className="form">
          {TEXT_FIELDS.map(({ key, label, hint, rows }) => (
            <Field key={key} label={label} hint={hint}>
              <textarea rows={rows} value={form[key] ?? ''} onChange={(e) => setForm({ ...form, [key]: e.target.value })} />
            </Field>
          ))}
        </div>
      </Card>
      <Card>
        <div className="row row-between">
          <h3>Exceptions</h3>
          <Button
            variant="ghost"
            onClick={() => setForm({ ...form, per_act_overrides: [...form.per_act_overrides, { when: '', change: '' }] })}
          >
            Add an exception
          </Button>
        </div>
        <p className="muted">Deliberate changes of look for part of the story, such as a flashback or archival footage.</p>
        {form.per_act_overrides.length === 0 && <span className="muted">None.</span>}
        {form.per_act_overrides.map((o, index) => (
          <div className="form" key={index}>
            <input value={o.when ?? ''} placeholder="Where in the story" aria-label="Where in the story" onChange={(e) => setOverride(index, { when: e.target.value })} />
            <textarea rows={2} value={o.change ?? ''} placeholder="How the look changes" aria-label="How the look changes" onChange={(e) => setOverride(index, { change: e.target.value })} />
            <div>
              <Button variant="ghost" onClick={() => setForm({ ...form, per_act_overrides: form.per_act_overrides.filter((_, i) => i !== index) })}>
                Remove
              </Button>
            </div>
          </div>
        ))}
      </Card>
      <Card>
        <div className="row">
          <Button variant="primary" busy={saving} disabled={!dirty} onClick={() => onSave(form)}>Save changes</Button>
          <Button busy={approving} disabled={dirty || approved || !bible.medium || !bible.art_style} onClick={onApprove}>
            Approve style
          </Button>
          {dirty && <Button variant="ghost" onClick={() => setForm(original)}>Discard changes</Button>}
          <Button variant="ghost" busy={generating} onClick={() => (approved ? setConfirmRegenerate(true) : onRegenerate())}>
            Write a new one
          </Button>
        </div>
        {dirty && <span className="muted">Save your changes before approving.</span>}
        {confirmRegenerate && (
          <Notice tone="warn">
            This replaces the approved style. Images made from the old style stay as they are.
            <div className="row">
              <Button variant="danger" busy={generating} onClick={() => { setConfirmRegenerate(false); onRegenerate() }}>Replace it</Button>
              <Button variant="ghost" onClick={() => setConfirmRegenerate(false)}>Keep the current one</Button>
            </div>
          </Notice>
        )}
      </Card>
      {block && (
        <Card>
          <h3>What the image prompts will start with</h3>
          <pre className="muted" style={{ whiteSpace: 'pre-wrap', margin: 0 }}>{block}</pre>
          {bible.negative_style && <span className="muted">Avoid: {bible.negative_style}</span>}
        </Card>
      )}
    </>
  )
}
