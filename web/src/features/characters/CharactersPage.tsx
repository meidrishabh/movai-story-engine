import { useState } from 'react'

import { Badge, Button, Card, Empty, ErrorNote, Loading, Notice, PageHeader } from '../../shared/ui'
import { plural } from '../../shared/lib/format'
import { useSeriesId } from '../series/api'
import { useEntities, useMergeEntity, useUpdateEntity } from './api'
import { useAppearance, useGenerateAppearance, useSaveAppearance, type AppearanceInput, type AppearanceSheet as Sheet } from './appearance'
import { AppearanceSheet } from './AppearanceSheet'
import type { Entity, EntityKind, ReviewStatus } from './types'

const TABS: { kind: EntityKind; label: string; key: 'characters' | 'locations' | 'objects' }[] = [
  { kind: 'character', label: 'Characters', key: 'characters' },
  { kind: 'location', label: 'Places', key: 'locations' },
  { kind: 'object', label: 'Objects', key: 'objects' },
]

const STATUS_TONE: Record<ReviewStatus, 'ok' | 'warn' | 'neutral'> = { approved: 'ok', needs_review: 'warn', stale: 'neutral', pending: 'neutral' }

export default function CharactersPage() {
  const seriesId = useSeriesId()
  const entities = useEntities(seriesId)
  const [kind, setKind] = useState<EntityKind>('character')
  const update = useUpdateEntity(seriesId)
  const merge = useMergeEntity(seriesId)
  const [waiting, setWaiting] = useState(false)
  const appearance = useAppearance(seriesId, waiting)
  const saveLook = useSaveAppearance(seriesId)
  const readLooks = useGenerateAppearance(seriesId)

  if (entities.isPending) return <Loading />
  if (entities.isError) return <div className="page"><ErrorNote error={entities.error} onRetry={() => void entities.refetch()} /></div>

  const tab = TABS.find((t) => t.kind === kind) ?? TABS[0]
  const all = entities.data[tab.key]
  const live = all.filter((e) => e.merged_into_id === null)
  const total = TABS.reduce((n, t) => n + entities.data[t.key].length, 0)

  return (
    <div className="page">
      <PageHeader
        title="Characters & places"
        subtitle="Check what the analysis found. Edits you make are kept when the story is analysed again."
        actions={
          <Button busy={readLooks.isPending} disabled={total === 0} onClick={() => readLooks.mutate(undefined, { onSuccess: () => setWaiting(true) })}>
            Read how characters look
          </Button>
        }
      />
      {readLooks.isError && <ErrorNote error={readLooks.error} />}
      {waiting && (
        <Notice tone="warn">
          <span>Reading the story for how characters look. This takes a few minutes; looks appear as they finish. Your own edits are kept.</span>
          <Button variant="ghost" onClick={() => setWaiting(false)}>Hide</Button>
        </Notice>
      )}

      {total === 0 && <Empty title="Nothing found yet">Characters, places and objects appear when the analysis finishes.</Empty>}

      {total > 0 && (
        <>
          <div className="row" role="tablist" aria-label="Kind">
            {TABS.map((t) => (
              <Button key={t.kind} role="tab" aria-selected={t.kind === kind} variant={t.kind === kind ? 'primary' : 'secondary'} onClick={() => setKind(t.kind)}>
                {t.label} ({entities.data[t.key].filter((e) => e.merged_into_id === null).length})
              </Button>
            ))}
          </div>
          {update.isError && <ErrorNote error={update.error} />}
          {merge.isError && <ErrorNote error={merge.error} />}
          {live.length === 0 && <Empty title="None of these yet" />}
          <div className="grid">
            {live.map((entity) => (
              <EntityCard
                key={entity.id}
                entity={entity}
                others={live.filter((o) => o.id !== entity.id)}
                busy={update.isPending || merge.isPending}
                look={kind === 'character' ? { sheet: appearance.data?.get(entity.id), busy: saveLook.isPending, onSave: (sheet) => saveLook.mutate({ characterId: entity.id, sheet }) } : undefined}
                onSave={(changes) => update.mutate({ kind, id: entity.id, changes })}
                onMerge={(intoId) => merge.mutate({ kind, id: entity.id, intoId })}
              />
            ))}
          </div>
        </>
      )}
    </div>
  )
}

interface CardProps {
  entity: Entity
  others: Entity[]
  busy: boolean
  onSave: (changes: { name?: string; description?: string; review_status?: ReviewStatus }) => void
  onMerge: (intoId: string) => void
  look?: { sheet: Sheet | undefined; busy: boolean; onSave: (sheet: AppearanceInput) => void }
}

function EntityCard({ entity, others, busy, onSave, onMerge, look }: CardProps) {
  const [editing, setEditing] = useState(false)
  const [name, setName] = useState(entity.name)
  const [description, setDescription] = useState(entity.description ?? '')
  const [mergeInto, setMergeInto] = useState('')

  const approved = entity.review_status === 'approved'

  return (
    <Card>
      <div className="row row-between">
        <h3>{entity.name}</h3>
        <Badge tone={STATUS_TONE[entity.review_status]}>{entity.review_status.replace('_', ' ')}</Badge>
      </div>
      {editing ? (
        <div className="form">
          <input value={name} onChange={(e) => setName(e.target.value)} aria-label="Name" />
          <textarea rows={3} value={description} onChange={(e) => setDescription(e.target.value)} aria-label="Description" />
          <div className="row">
            <Button
              variant="primary"
              busy={busy}
              disabled={!name.trim()}
              onClick={() => {
                onSave({ name: name.trim(), description })
                setEditing(false)
              }}
            >
              Save
            </Button>
            <Button variant="ghost" onClick={() => setEditing(false)}>Cancel</Button>
          </div>
        </div>
      ) : (
        <>
          {(entity.disambiguation || entity.story_role) && <span className="muted">{[entity.disambiguation, entity.story_role].filter(Boolean).join(' · ')}</span>}
          {entity.description && <p className="muted">{entity.description}</p>}
          {entity.aliases.length > 0 && (
            <div className="row">
              {entity.aliases.map((a) => (
                <Badge key={a}>{a}</Badge>
              ))}
            </div>
          )}
          <span className="muted">{plural(entity.mention_count, 'mention')}</span>
          {look && <AppearanceSheet sheet={look.sheet} busy={look.busy} onSave={look.onSave} />}
          <div className="row">
            <Button busy={busy} onClick={() => onSave({ review_status: approved ? 'needs_review' : 'approved' })}>
              {approved ? 'Mark for review' : 'Approve'}
            </Button>
            <Button variant="ghost" onClick={() => setEditing(true)}>Edit</Button>
          </div>
          {others.length > 0 && (
            <div className="row">
              <select value={mergeInto} onChange={(e) => setMergeInto(e.target.value)} aria-label={`Merge ${entity.name} into`}>
                <option value="">Same as…</option>
                {others.map((o) => (
                  <option key={o.id} value={o.id}>{o.name}</option>
                ))}
              </select>
              <Button variant="ghost" disabled={!mergeInto || busy} onClick={() => onMerge(mergeInto)}>Merge</Button>
            </div>
          )}
        </>
      )}
    </Card>
  )
}
