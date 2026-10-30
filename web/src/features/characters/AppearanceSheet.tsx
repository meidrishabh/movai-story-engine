import { useState } from 'react'

import { Badge, Button } from '../../shared/ui'
import type { AppearanceInput, AppearanceSheet as Sheet } from './appearance'

const ROWS: { label: string; field: 'face_and_body_design' | 'clothing_and_accessories' | 'distinctive_features' | 'voice' }[] = [
  { label: 'Face and body', field: 'face_and_body_design' },
  { label: 'Clothing', field: 'clothing_and_accessories' },
  { label: 'Distinctive', field: 'distinctive_features' },
  { label: 'Voice', field: 'voice' },
]

interface Props {
  sheet: Sheet | undefined
  busy: boolean
  onSave: (sheet: AppearanceInput) => void
}

/** How a character looks and sounds, as the story describes them. Empty means the story does not say. */
export function AppearanceSheet({ sheet, busy, onSave }: Props) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState<AppearanceInput>(() => toInput(sheet))

  if (editing) {
    const set = (patch: Partial<AppearanceInput>) => setDraft({ ...draft, ...patch })
    return (
      <div className="form appearance">
        <textarea rows={2} value={draft.description} onChange={(e) => set({ description: e.target.value })} aria-label="Overall look" placeholder="Overall look" />
        {ROWS.map(({ label, field }) => (
          <input key={field} value={draft[field] ?? ''} onChange={(e) => set({ [field]: e.target.value || null })} aria-label={label} placeholder={label} />
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
        <p className="muted">The story does not describe how they look.</p>
      ) : (
        <>
          <p className="muted">{sheet.description}</p>
          <dl className="facts">
            {ROWS.filter(({ field }) => sheet[field]).map(({ label, field }) => (
              <div key={field}>
                <dt>{label}</dt>
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
          {sheet.costumes.length > 0 && (
            <ul className="event-list">
              {sheet.costumes.map((c) => (
                <li key={c.id}>
                  <strong>{c.name}</strong> <span className="muted">{c.description}{c.when ? ` (${c.when})` : ''}</span>
                </li>
              ))}
            </ul>
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

function toInput(sheet: Sheet | undefined): AppearanceInput {
  return {
    description: sheet?.description ?? '',
    face_and_body_design: sheet?.face_and_body_design ?? null,
    clothing_and_accessories: sheet?.clothing_and_accessories ?? null,
    distinctive_features: sheet?.distinctive_features ?? null,
    color_palette: sheet?.color_palette ?? [],
    voice: sheet?.voice ?? null,
  }
}
