import { useState } from 'react'

import { Badge, Button } from '../../shared/ui'
import type { LookInput, LookSheet } from './appearance'

type Field = 'form' | 'atmosphere' | 'distinctive_features'

const LABELS: Record<'location' | 'object', Record<Field, string>> = {
  location: { form: 'Layout and build', atmosphere: 'Mood and light', distinctive_features: 'Landmarks' },
  object: { form: 'Shape and material', atmosphere: 'Condition', distinctive_features: 'Marks and details' },
}
const FIELDS: Field[] = ['form', 'atmosphere', 'distinctive_features']

interface Props {
  kind: 'location' | 'object'
  sheet: LookSheet | undefined
  busy: boolean
  onSave: (sheet: LookInput) => void
}

/** How a place or an object looks, as the story describes it. Empty means the story does not say. */
export function ThingLook({ kind, sheet, busy, onSave }: Props) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState<LookInput>(() => toInput(sheet))
  const labels = LABELS[kind]

  if (editing) {
    const set = (patch: Partial<LookInput>) => setDraft({ ...draft, ...patch })
    return (
      <div className="form appearance">
        <textarea rows={2} value={draft.description} onChange={(e) => set({ description: e.target.value })} aria-label="Overall look" placeholder="Overall look" />
        {FIELDS.map((field) => (
          <input key={field} value={draft[field] ?? ''} onChange={(e) => set({ [field]: e.target.value || null })} aria-label={labels[field]} placeholder={labels[field]} />
        ))}
        <input
          value={draft.color_palette.join(', ')}
          onChange={(e) => set({ color_palette: e.target.value.split(',').map((c) => c.trim()).filter(Boolean) })}
          aria-label="Colours"
          placeholder="Colours, comma separated"
        />
        <div className="row">
          <Button
            variant="primary"
            busy={busy}
            disabled={!draft.description.trim()}
            onClick={() => {
              onSave(draft)
              setEditing(false)
            }}
          >
            Save look
          </Button>
          <Button variant="ghost" onClick={() => setEditing(false)}>Cancel</Button>
        </div>
      </div>
    )
  }

  return (
    <div className="appearance">
      <div className="row row-between">
        <strong>Look</strong>
        {sheet && <Badge tone={sheet.status === 'approved' ? 'ok' : 'accent'}>{sheet.status === 'approved' ? 'yours' : 'from the story'}</Badge>}
      </div>
      {!sheet ? (
        <p className="muted">The story does not describe how it looks.</p>
      ) : (
        <>
          <p className="muted">{sheet.description}</p>
          <dl className="facts">
            {FIELDS.filter((field) => sheet[field]).map((field) => (
              <div key={field}>
                <dt>{labels[field]}</dt>
                <dd>{sheet[field]}</dd>
              </div>
            ))}
          </dl>
          {sheet.color_palette.length > 0 && (
            <div className="row">
              {sheet.color_palette.map((c) => (
                <Badge key={c}>{c}</Badge>
              ))}
            </div>
          )}
          {sheet.status === 'draft' && sheet.change_notes && <p className="muted fine">{sheet.change_notes}</p>}
        </>
      )}
      <Button
        variant="ghost"
        onClick={() => {
          setDraft(toInput(sheet))
          setEditing(true)
        }}
      >
        {sheet ? 'Edit look' : 'Add look'}
      </Button>
    </div>
  )
}

function toInput(sheet: LookSheet | undefined): LookInput {
  return {
    description: sheet?.description ?? '',
    form: sheet?.form ?? null,
    atmosphere: sheet?.atmosphere ?? null,
    distinctive_features: sheet?.distinctive_features ?? null,
    color_palette: sheet?.color_palette ?? [],
  }
}
