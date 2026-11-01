import { useState } from 'react'
import { Link } from 'react-router-dom'

import { env } from '../../config/env'
import { Badge, Button, Card, Empty, ErrorNote, Loading, Notice, PageHeader } from '../../shared/ui'
import { ReferenceScopePanel } from '../scope/ReferenceScopePanel'
import { useSeriesId } from '../series/api'
import { useReferenceActions, useReferences } from './api'
import './references.css'
import type { RefRequest, RefTarget, RefView } from './types'

type Tab = 'anchors' | 'characters' | 'places' | 'objects'
type Actions = ReturnType<typeof useReferenceActions>

const TABS: { key: Tab; label: string }[] = [
  { key: 'anchors', label: 'Style anchors' },
  { key: 'characters', label: 'Characters' },
  { key: 'places', label: 'Places' },
  { key: 'objects', label: 'Objects' },
]

const imageUrl = (request: RefRequest) => (request.result ? `${env.apiUrl}${request.result.url}` : null)
const percent = (score: number | null) => (score === null ? null : `${Math.round(score * 100)}%`)

function hasFlag(target: RefTarget): boolean {
  const views = [...target.views, ...(target.costumes ?? []).flatMap((c) => c.views)]
  return views.some((v) => v.request?.drift_flag && v.request.review_status === 'pending')
}

export default function ReferencesPage() {
  const seriesId = useSeriesId()
  const query = useReferences(seriesId)
  const actions = useReferenceActions(seriesId)
  const [tab, setTab] = useState<Tab>('anchors')
  const [flaggedOnly, setFlaggedOnly] = useState(false)

  if (query.isPending) return <Loading />
  if (query.isError) return <div className="page"><ErrorNote error={query.error} onRetry={() => void query.refetch()} /></div>
  const data = query.data
  const hasAnchor = data.style_anchor_asset_id !== null
  const error = [actions.generateAll, actions.generate, actions.review, actions.retry, actions.recheck, actions.pickAnchor, actions.generateAnchors]
    .find((m) => m.isError)?.error

  return (
    <div className="page">
      <PageHeader
        title="Reference images"
        subtitle="The approved pictures of every character, place and object. Every shot is made from these, so the look stays the same."
        actions={
          <Button
            variant="primary"
            busy={actions.generateAll.isPending}
            disabled={!hasAnchor}
            title={hasAnchor ? undefined : 'Pick a style anchor first'}
            onClick={() => actions.generateAll.mutate()}
          >
            Generate all references
          </Button>
        }
      />
      {error !== undefined && <ErrorNote error={error} />}
      {actions.generateAll.isSuccess && (
        <Notice tone="ok">
          {actions.generateAll.data.requests_created === 0
            ? 'Everything is already requested.'
            : `Requested ${actions.generateAll.data.requests_created} pictures. Other views of a subject start once you approve its first one.`}
          {!!actions.generateAll.data.left_out_of_scope && ` ${actions.generateAll.data.left_out_of_scope} left out by your selection.`}
        </Notice>
      )}
      <ReferenceScopePanel seriesId={seriesId} data={data} />
      {!data.style_bible_approved && (
        <Notice tone="warn">
          The style bible is not approved yet. <Link to="../style">Approve it first</Link>: every picture is made from it.
        </Notice>
      )}
      <div className="row row-between">
        <div className="row" role="tablist" aria-label="Kind">
          {TABS.map((t) => (
            <Button key={t.key} role="tab" aria-selected={t.key === tab} variant={t.key === tab ? 'primary' : 'secondary'} onClick={() => setTab(t.key)}>
              {t.label}
            </Button>
          ))}
        </div>
        {tab !== 'anchors' && (
          <label className="row">
            <input type="checkbox" checked={flaggedOnly} onChange={(e) => setFlaggedOnly(e.target.checked)} />
            Only images that drift from their references{data.flagged_count > 0 && <Badge tone="warn">{data.flagged_count}</Badge>}
          </label>
        )}
      </div>

      {tab === 'anchors' ? (
        <AnchorsTab approvedBible={data.style_bible_approved} anchors={data.style_anchors} anchorId={data.style_anchor_asset_id} actions={actions} />
      ) : (
        <TargetsTab
          targets={tab === 'characters' ? data.characters : tab === 'places' ? data.places : data.objects}
          kindLabel={tab}
          flaggedOnly={flaggedOnly}
          hasAnchor={hasAnchor}
          actions={actions}
        />
      )}
    </div>
  )
}

function AnchorsTab({ approvedBible, anchors, anchorId, actions }: { approvedBible: boolean; anchors: RefRequest[]; anchorId: string | null; actions: Actions }) {
  const live = anchors.filter((a) => a.status !== 'rejected')
  return (
    <>
      <Card>
        <div className="row row-between">
          <div>
            <h3>Style anchor</h3>
            <p className="muted">One frame that shows the look of the whole series. It is attached to every other picture. Make a few, then pick the one that looks right.</p>
          </div>
          <Button busy={actions.generateAnchors.isPending} disabled={!approvedBible} onClick={() => actions.generateAnchors.mutate(4)}>
            {live.length > 0 ? 'Make new candidates' : 'Make 4 candidates'}
          </Button>
        </div>
      </Card>
      {live.length === 0 ? (
        <Empty title="No candidates yet">Make a few frames to choose from.</Empty>
      ) : (
        <div className="ref-grid">
          {live.map((anchor) => (
            <ImageCell
              key={anchor.id}
              label={anchor.review_status === 'approved' ? 'Current anchor' : 'Candidate'}
              request={anchor}
              isCurrent={anchor.result?.id === anchorId}
              actions={actions}
              pick={() => actions.pickAnchor.mutate(anchor.id)}
            />
          ))}
        </div>
      )}
    </>
  )
}

function TargetsTab({ targets, kindLabel, flaggedOnly, hasAnchor, actions }: { targets: RefTarget[]; kindLabel: string; flaggedOnly: boolean; hasAnchor: boolean; actions: Actions }) {
  const shown = flaggedOnly ? targets.filter(hasFlag) : targets
  if (targets.length === 0) {
    return <Empty title={`No ${kindLabel} yet`}>Look sheets are written in the Characters &amp; places step. They appear here once they exist.</Empty>
  }
  if (shown.length === 0) return <Empty title="Nothing drifts">No image differs noticeably from its approved references.</Empty>
  return (
    <>
      {!hasAnchor && <Notice tone="warn">Pick a style anchor first. Pictures cannot be requested until you do.</Notice>}
      {shown.map((target) => (
        <Card key={target.target_id}>
          <div className="row row-between">
            <div>
              <h3>{target.name}</h3>
              <p className="muted ref-desc">{target.description}</p>
            </div>
            <Button variant="ghost" disabled={!hasAnchor} onClick={() => actions.generate.mutate({ target })}>
              Request missing views
            </Button>
          </div>
          <ViewGrid target={target} views={target.views} actions={actions} />
          {(target.costumes ?? []).map((costume) => (
            <div key={costume.target_id} className="stack">
              <strong>Costume: {costume.name}</strong>
              <ViewGrid target={costume} views={costume.views} actions={actions} />
            </div>
          ))}
        </Card>
      ))}
    </>
  )
}

function ViewGrid({ target, views, actions }: { target: Pick<RefTarget, 'target_type' | 'target_id'>; views: RefView[]; actions: Actions }) {
  const first = views[0]
  return (
    <div className="ref-grid">
      {views.map((view) => (
        <ImageCell
          key={view.view}
          label={view.label}
          request={view.request}
          waitingFor={view.view !== first.view ? first.label : undefined}
          attempts={view.attempts}
          actions={actions}
          generate={(force) => actions.generate.mutate({ target, views: [view.view], force })}
        />
      ))}
    </div>
  )
}

interface CellProps {
  label: string
  request: RefRequest | null
  actions: Actions
  isCurrent?: boolean
  waitingFor?: string
  attempts?: number
  generate?: (force: boolean) => void
  pick?: () => void
}

function ImageCell({ label, request, actions, isCurrent, waitingFor, attempts, generate, pick }: CellProps) {
  const [rejecting, setRejecting] = useState(false)
  const [note, setNote] = useState('')
  const url = request ? imageUrl(request) : null
  const flagged = !!request?.drift_flag && request.review_status === 'pending'
  const done = request?.status === 'succeeded'
  const approved = request?.review_status === 'approved'
  const busy = actions.review.isPending || actions.retry.isPending

  return (
    <div className={`ref-cell${flagged ? ' ref-flagged' : ''}${isCurrent ? ' ref-current' : ''}`}>
      <div className="ref-frame">
        {url ? (
          <img src={url} alt={`${label} reference`} loading="lazy" />
        ) : (
          <span className="muted">{placeholder(request, waitingFor)}</span>
        )}
      </div>
      <div className="row row-between">
        <strong>{label}</strong>
        <span className="row" style={{ gap: 6 }}>
          {approved && <Badge tone="ok">Approved</Badge>}
          {done && !approved && <Badge tone="neutral">Needs review</Badge>}
          {flagged && <Badge tone="warn">Drift {percent(request?.drift_score ?? null)}</Badge>}
          {(attempts ?? 0) > 1 && <Badge tone="neutral">attempt {attempts}</Badge>}
        </span>
      </div>
      {flagged && request?.drift_notes && <p className="muted ref-note">{request.drift_notes}</p>}
      {!flagged && done && request?.drift_score != null && (
        <p className="muted ref-note">Match with references {percent(request.drift_score)}{request.drift_judge === 'mock' ? ' (mock check)' : ''}</p>
      )}
      {request?.status === 'failed' && <p className="muted ref-note">{request.error_summary ?? 'Failed.'}</p>}

      <div className="row" style={{ gap: 6 }}>
        {!request && generate && <Button onClick={() => generate(false)}>Generate</Button>}
        {request?.status === 'failed' && <Button busy={busy} onClick={() => actions.retry.mutate(request.id)}>Retry</Button>}
        {request && done && !approved && pick && <Button variant="primary" onClick={pick}>Pick this one</Button>}
        {request && done && !approved && !pick && (
          <Button variant="primary" busy={busy} onClick={() => actions.review.mutate({ requestId: request.id, decision: 'approve' })}>Approve</Button>
        )}
        {done && !approved && <Button variant="ghost" onClick={() => setRejecting(!rejecting)}>Reject…</Button>}
        {done && approved && generate && <Button variant="ghost" onClick={() => generate(true)}>Regenerate</Button>}
        {request && flagged && (
          <Button variant="ghost" busy={actions.recheck.isPending} onClick={() => actions.recheck.mutate(request.id)}>Re-check</Button>
        )}
      </div>
      {rejecting && request && (
        <div className="stack">
          <textarea rows={2} value={note} placeholder="What is wrong? The next attempt gets this note." onChange={(e) => setNote(e.target.value)} />
          <div className="row" style={{ gap: 6 }}>
            <Button
              variant="danger"
              busy={busy}
              onClick={() => actions.review.mutate({ requestId: request.id, decision: 'reject', note: note.trim() || undefined }, { onSuccess: () => { setRejecting(false); setNote('') } })}
            >
              Reject and try again
            </Button>
            <Button variant="ghost" onClick={() => setRejecting(false)}>Cancel</Button>
          </div>
        </div>
      )}
    </div>
  )
}

function placeholder(request: RefRequest | null, waitingFor?: string): string {
  if (!request) return 'Not requested'
  switch (request.status) {
    case 'queued':
    case 'running':
      return 'Making the picture…'
    case 'blocked':
      return waitingFor ? `Waiting for you to approve the ${waitingFor.toLowerCase()} view` : 'Waiting'
    case 'awaiting_input':
      return 'Waiting for an upload'
    case 'failed':
      return 'Failed'
    default:
      return 'No picture'
  }
}
