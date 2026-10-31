import { useState } from 'react'

import { Badge, Button, Card, ErrorNote } from '../../shared/ui'
import { useBreakdownOverview } from '../breakdown/api'
import type { ReferenceOverview, RefTarget } from '../references/types'
import { useScopeActions } from './api'
import './scope.css'

/**
 * Choose which characters, places and objects get reference images. "Generate all references" then makes only those.
 * Shots that show something left out are made without a reference picture of it.
 */
export function ReferenceScopePanel({ seriesId, data }: { seriesId: string; data: ReferenceOverview }) {
  const actions = useScopeActions(seriesId)
  const episodes = useBreakdownOverview(seriesId)
  const limited = data.scope?.limited ?? false
  const [open, setOpen] = useState(false)
  const [episodeId, setEpisodeId] = useState('')

  const chosen = {
    characters: data.characters.filter((t) => t.in_scope !== false && t.character_id).map((t) => t.character_id as string),
    costumes: data.characters.flatMap((t) => t.costumes ?? []).filter((c) => c.in_scope !== false).map((c) => c.target_id),
    places: data.places.filter((t) => t.in_scope !== false && t.entity_id).map((t) => t.entity_id as string),
    objects: data.objects.filter((t) => t.in_scope !== false && t.entity_id).map((t) => t.entity_id as string),
  }
  const save = (next: Partial<typeof chosen>) => actions.setReferenceScope.mutate({ limited: true, ...chosen, ...next })
  const flip = (list: string[], id: string) => (list.includes(id) ? list.filter((x) => x !== id) : [...list, id])
  const picks = episodes.data?.filter((e) => e.scene_count > 0) ?? []
  const error = [actions.setReferenceScope, actions.selectForScenes].find((m) => m.isError)?.error

  const group = (label: string, key: 'characters' | 'places' | 'objects', targets: RefTarget[], idOf: (t: RefTarget) => string | undefined) =>
    targets.length === 0 ? null : (
      <div className="stack">
        <strong>{label}</strong>
        <ul className="scope-refs-list">
          {targets.map((t) => {
            const id = idOf(t)
            return id ? (
              <li key={t.target_id}>
                <label className="row">
                  <input type="checkbox" checked={chosen[key].includes(id)} onChange={() => save({ [key]: flip(chosen[key], id) })} />
                  {t.name}
                </label>
              </li>
            ) : null
          })}
        </ul>
      </div>
    )

  return (
    <Card>
      <div className="row row-between">
        <h3>What to make pictures for</h3>
        <div className="row">
          <Badge tone={limited ? 'accent' : 'neutral'}>{limited ? 'Only some' : 'Everything'}</Badge>
          <Button variant="ghost" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
            {open ? 'Hide' : 'Choose'}
          </Button>
        </div>
      </div>
      {!open && (
        <p className="muted">
          {limited
            ? 'Only the ticked characters, places and objects get reference images; the rest are skipped.'
            : 'Every character, place and object gets reference images. Choose some to test with fewer.'}
        </p>
      )}
      {open && (
        <div className="stack">
          <div className="row scope-refs">
            <select aria-label="Episode" className="input" value={episodeId} onChange={(e) => setEpisodeId(e.target.value)}>
              <option value="">Pick an episode…</option>
              {picks.map((e) => (
                <option key={e.id} value={e.id}>
                  Episode {e.episode_number}
                </option>
              ))}
            </select>
            <Button busy={actions.selectForScenes.isPending} disabled={!episodeId} onClick={() => actions.selectForScenes.mutate(episodeId)}>
              Only what its chosen scenes need
            </Button>
            <Button variant="ghost" busy={actions.setReferenceScope.isPending} disabled={!limited} onClick={() => actions.setReferenceScope.mutate({ limited: false })}>
              Make everything
            </Button>
          </div>
          {group('Characters', 'characters', data.characters, (t) => t.character_id)}
          {group('Places', 'places', data.places, (t) => t.entity_id)}
          {group('Objects', 'objects', data.objects, (t) => t.entity_id)}
        </div>
      )}
      {error !== undefined && <ErrorNote error={error} />}
    </Card>
  )
}
