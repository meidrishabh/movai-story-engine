import { useState } from 'react'

import { Badge, Button, Card, ErrorNote, Loading, Notice } from '../../shared/ui'
import { formatDuration, plural } from '../../shared/lib/format'
import { useScopeActions, useWorkingScenes } from './api'
import type { ChecklistStage, ScopeChecklist } from './types'
import './scope.css'

/**
 * Choose which scenes of an episode to work on. Keyframes, clips, sound and renders of the episode then cover only those
 * scenes, and "Generate for selected scenes" also narrows the reference images to what those scenes show.
 */
export function ScenePicker({ seriesId, episodeId }: { seriesId: string; episodeId: string }) {
  const query = useWorkingScenes(episodeId)
  const actions = useScopeActions(seriesId, episodeId)
  const [draft, setDraft] = useState<string[] | null>(null)
  const [open, setOpen] = useState(false)

  if (query.isPending) return <Loading />
  if (query.isError) return <ErrorNote error={query.error} onRetry={() => void query.refetch()} />
  const data = query.data
  const chosen = draft ?? data.scene_ids
  const dirty = draft !== null && [...draft].sort().join() !== [...data.scene_ids].sort().join()
  const toggle = (id: string) => setDraft(chosen.includes(id) ? chosen.filter((x) => x !== id) : [...chosen, id])
  const chosenShots = data.scenes.filter((s) => chosen.includes(s.id)).reduce((n, s) => n + s.shots, 0)
  const checklist = actions.prepare.data?.checklist
  const error = [actions.setScenes, actions.prepare].find((m) => m.isError)?.error

  return (
    <Card>
      <div className="row row-between">
        <h3>Scenes to work on</h3>
        <div className="row">
          {data.all_scenes ? <Badge tone="neutral">Whole episode</Badge> : <Badge tone="accent">{plural(data.scene_ids.length, 'scene')} · {plural(data.selected_shots, 'shot')}</Badge>}
          <Button variant="ghost" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
            {open ? 'Hide' : 'Choose scenes'}
          </Button>
        </div>
      </div>
      {!open && (
        <p className="muted">
          {data.all_scenes
            ? 'Everything in this episode is included. Choose scenes to try the pipeline on a small part first.'
            : 'Keyframes, clips, sound and renders cover only the chosen scenes. The final export needs approved clips for these shots only.'}
        </p>
      )}
      {open && (
        <div className="stack">
          <div className="row scope-quick">
            <Button variant="ghost" onClick={() => setDraft(data.scenes.slice(0, 1).map((s) => s.id))}>First scene</Button>
            <Button variant="ghost" onClick={() => setDraft(data.scenes.slice(0, 2).map((s) => s.id))}>First two</Button>
            <Button variant="ghost" onClick={() => setDraft(data.scenes.map((s) => s.id))}>All</Button>
            <Button variant="ghost" onClick={() => setDraft([])}>None</Button>
          </div>
          <ul className="scope-scenes">
            {data.scenes.map((s) => (
              <li key={s.id}>
                <label className="row">
                  <input type="checkbox" checked={chosen.includes(s.id)} onChange={() => toggle(s.id)} />
                  <span>
                    Scene {s.scene_number} <span className="muted">· {s.title}</span>
                  </span>
                  <span className="muted mono">
                    {plural(s.shots, 'shot')} · {formatDuration(s.seconds)}
                  </span>
                </label>
              </li>
            ))}
          </ul>
          <div className="row">
            <Button
              busy={actions.setScenes.isPending}
              disabled={!dirty}
              onClick={() => actions.setScenes.mutate(chosen.length === data.scenes.length ? [] : chosen, { onSuccess: () => setDraft(null) })}
            >
              Save selection
            </Button>
            <Button
              variant="primary"
              busy={actions.prepare.isPending}
              disabled={chosen.length === 0}
              title="Saves the scenes, limits reference images to the characters, places and objects they show, and queues the missing ones"
              onClick={() => actions.prepare.mutate({ sceneIds: chosen, requestReferences: true }, { onSuccess: () => setDraft(null) })}
            >
              Generate for selected scenes
            </Button>
            <span className="muted">{chosen.length === 0 ? 'Nothing chosen: this means the whole episode.' : `${plural(chosenShots, 'shot')} selected`}</span>
          </div>
        </div>
      )}
      {error !== undefined && <ErrorNote error={error} />}
      {checklist && <Checklist checklist={checklist} requested={actions.prepare.data?.references_requested ?? null} />}
    </Card>
  )
}

function Checklist({ checklist, requested }: { checklist: ScopeChecklist; requested: { requests_created?: number; error?: string } | null }) {
  return (
    <div className="stack scope-checklist">
      {requested?.error && <Notice tone="warn">{requested.error}</Notice>}
      {requested?.requests_created !== undefined && (
        <Notice tone="ok">{requested.requests_created === 0 ? 'No new reference images were needed.' : `${plural(requested.requests_created, 'reference image')} requested.`}</Notice>
      )}
      <strong>
        What these scenes still need {checklist.ready_to_render && <Badge tone="ok">Ready to render</Badge>}
      </strong>
      <ul className="scope-stages">
        {checklist.stages.map((stage) => (
          <StageRow key={stage.key} stage={stage} />
        ))}
      </ul>
    </div>
  )
}

function StageRow({ stage }: { stage: ChecklistStage }) {
  return (
    <li>
      <div className="row row-between">
        <span>{stage.label}</span>
        <Badge tone={stage.complete ? 'ok' : 'warn'}>
          {stage.done}/{stage.total}
        </Badge>
      </div>
      {!stage.complete && stage.missing.length > 0 && (
        <p className="muted">
          Missing: {stage.missing.slice(0, 6).join(', ')}
          {stage.missing_count > 6 ? ` and ${stage.missing_count - 6} more` : ''} · {stage.hint}
        </p>
      )}
    </li>
  )
}
