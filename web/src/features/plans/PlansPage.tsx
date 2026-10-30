import { useState } from 'react'

import { Badge, Button, Card, Empty, ErrorNote, Loading, Notice, PageHeader } from '../../shared/ui'
import { formatDuration, plural } from '../../shared/lib/format'
import { useSeriesId } from '../series/api'
import { useApproveAll, useApprovePlan, useRejectPlan, usePlans, useReplan } from './api'
import type { EpisodePlan, PlanStatus } from './types'

const TONE: Record<PlanStatus, 'accent' | 'ok' | 'bad'> = { draft: 'accent', approved: 'ok', rejected: 'bad' }

export default function PlansPage() {
  const seriesId = useSeriesId()
  const [waiting, setWaiting] = useState(false)
  const plans = usePlans(seriesId, waiting)
  const approve = useApprovePlan(seriesId)
  const approveAll = useApproveAll(seriesId)
  const reject = useRejectPlan(seriesId)
  const replan = useReplan(seriesId)

  if (plans.isPending) return <Loading />
  if (plans.isError) return <div className="page"><ErrorNote error={plans.error} onRetry={() => void plans.refetch()} /></div>

  const drafts = plans.data.filter((p) => p.status === 'draft')
  const seasons = groupBySeason(plans.data)

  return (
    <div className="page">
      <PageHeader
        title="Episode plans"
        subtitle="Nothing becomes an episode until you approve it."
        actions={
          <>
            <Button
              busy={replan.isPending}
              onClick={() => replan.mutate(undefined, { onSuccess: () => setWaiting(true) })}
            >
              Re-plan
            </Button>
            <Button variant="primary" busy={approveAll.isPending} disabled={drafts.length === 0} onClick={() => approveAll.mutate()}>
              Approve all drafts ({drafts.length})
            </Button>
          </>
        }
      />

      {replan.isError && <ErrorNote error={replan.error} />}
      {waiting && <Notice tone="warn">Planning again. This list updates when the new plans are ready.</Notice>}
      {approve.isError && <ErrorNote error={approve.error} />}
      {approveAll.isError && <ErrorNote error={approveAll.error} />}

      {plans.data.length === 0 && <Empty title="No plans yet">Plans appear when the analysis finishes.</Empty>}

      {seasons.map((season) => (
        <div className="stack" key={season.number}>
          <h2>
            Season {season.number}
            {season.title && <span className="muted"> · {season.title}</span>}
          </h2>
          {season.plans.map((plan) => (
            <PlanCard
              key={plan.id}
              plan={plan}
              onApprove={() => approve.mutate(plan.id)}
              onReject={(note) => reject.mutate({ planId: plan.id, note })}
              busy={(approve.isPending && approve.variables === plan.id) || (reject.isPending && reject.variables?.planId === plan.id)}
            />
          ))}
        </div>
      ))}
    </div>
  )
}

function groupBySeason(plans: EpisodePlan[]) {
  const seasons = new Map<number, { number: number; title: string | null; plans: EpisodePlan[] }>()
  for (const plan of plans) {
    const season = seasons.get(plan.season_number) ?? { number: plan.season_number, title: plan.season_title, plans: [] }
    season.plans.push(plan)
    seasons.set(plan.season_number, season)
  }
  return [...seasons.values()].sort((a, b) => a.number - b.number)
}

function PlanCard({ plan, busy, onApprove, onReject }: { plan: EpisodePlan; busy: boolean; onApprove: () => void; onReject: (note: string) => void }) {
  return (
    <Card>
      <div className="row row-between">
        <h3>
          <span className="muted mono">E{plan.episode_number}</span> {plan.title}
        </h3>
        <div className="row">
          <span className="muted mono">{formatDuration(plan.target_duration_seconds)}</span>
          <Badge tone={TONE[plan.status]}>{plan.status}</Badge>
        </div>
      </div>
      {plan.synopsis && <p>{plan.synopsis}</p>}
      <p className="muted">
        {plural(plan.unit_count, 'story unit')}
        {plan.characters.length > 0 && ` · ${plan.characters.slice(0, 6).join(', ')}`}
      </p>
      {plan.review_note && <p className="muted">Note: {plan.review_note}</p>}
      {plan.status === 'draft' && (
        <div className="row">
          <Button variant="primary" busy={busy} onClick={onApprove}>
            Approve
          </Button>
          <Button variant="danger" disabled={busy} onClick={() => onReject('Rejected from the review screen')}>
            Reject
          </Button>
        </div>
      )}
    </Card>
  )
}
