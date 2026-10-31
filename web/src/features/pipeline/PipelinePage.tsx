import { Link } from 'react-router-dom'

import { Badge, Card, Empty, ErrorNote, Loading, LinkButton, Notice, PageHeader, ProgressBar } from '../../shared/ui'
import { formatDate, plural } from '../../shared/lib/format'
import { useSeriesId } from '../series/api'
import { usePipeline } from './api'
import GenerationPanel from './GenerationPanel'
import { isRunActive, stageStates } from './stages'
import type { Attention } from './types'

export default function PipelinePage() {
  const seriesId = useSeriesId()
  const pipeline = usePipeline(seriesId)

  if (pipeline.isPending) return <Loading />
  if (pipeline.isError) return <div className="page"><ErrorNote error={pipeline.error} onRetry={() => void pipeline.refetch()} /></div>

  const run = pipeline.data.analysis_run
  if (!run) {
    return (
      <div className="page">
        <PageHeader title="Pipeline" />
        <Empty title="Nothing has been analysed yet">Upload a story and start the analysis first.</Empty>
        <div className="row"><LinkButton to="../upload" variant="primary">Go to upload</LinkButton></div>
      </div>
    )
  }

  const stages = stageStates(run)
  const active = isRunActive(run)

  return (
    <div className="page">
      <PageHeader
        title="Pipeline"
        subtitle={pipeline.data.source?.title}
        actions={
          run.status === 'succeeded' ? (
            <LinkButton to="../adaptation" variant="primary">Review the adaptation</LinkButton>
          ) : undefined
        }
      />

      <Card>
        <div className="row row-between">
          <div className="row">
            <Badge tone={run.status === 'succeeded' ? 'ok' : run.status === 'failed' ? 'bad' : 'accent'}>{run.status}</Badge>
            {run.model_name && <span className="muted mono">{run.model_name}</span>}
          </div>
          <span className="muted">{run.completed_at ? `Finished ${formatDate(run.completed_at)}` : `Started ${formatDate(run.started_at)}`}</span>
        </div>
        <ProgressBar value={run.progress} label="Analysis progress" />
        <ol className="stage-list">
          {stages.map((stage) => (
            <li key={stage.key} className={`stage stage-${stage.state}`}>
              <span className="stage-dot" aria-hidden />
              <span>{stage.label}</span>
              <span className="muted" style={{ marginLeft: 'auto' }}>
                {stage.state === 'done' ? 'Done' : stage.state === 'active' ? 'Working…' : stage.state === 'failed' ? 'Failed' : ''}
              </span>
            </li>
          ))}
        </ol>
      </Card>

      {run.status === 'failed' && <ErrorNote error={new Error(run.error_message ?? 'The analysis failed.')} />}
      {run.status === 'succeeded' && (
        <Notice>
          Analysis finished. Review the adaptation and the episode plans before anything is approved.
        </Notice>
      )}
      {run.status === 'succeeded' && <AttentionList attention={pipeline.data.attention} />}
      {run.status === 'succeeded' && <GenerationPanel seriesId={seriesId} />}
      {active && <p className="muted">This page updates by itself. Long stories can take several minutes.</p>}
    </div>
  )
}

function AttentionList({ attention }: { attention: Attention }) {
  const items = [
    { count: attention.disputed_beats, text: (n: number) => `${plural(n, 'beat')} the two reviewers disagreed on`, to: '../adaptation' },
    { count: attention.open_conflicts, text: (n: number) => `${plural(n, 'continuity conflict')} to check`, to: '../structure' },
    { count: attention.entities_to_review, text: (n: number) => `${plural(n, 'character, place or object')} marked for review`, to: '../characters' },
    { count: attention.draft_plans, text: (n: number) => `${plural(n, 'episode plan')} waiting for approval`, to: '../plans' },
  ]
    .filter((item) => item.count > 0)
    .concat(attention.generation.map((item) => ({ count: item.count, text: () => item.label, to: item.to })))
  if (items.length === 0) return <Notice>Nothing needs your attention.</Notice>
  return (
    <Card>
      <h2>Needs your attention</h2>
      <ul className="event-list">
        {items.map((item) => (
          <li key={`${item.to}-${item.text(item.count)}`}>
            <Link to={item.to}>{item.text(item.count)}</Link>
          </li>
        ))}
      </ul>
    </Card>
  )
}
