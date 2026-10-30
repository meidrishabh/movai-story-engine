import { Badge, Card, Empty, ErrorNote, Loading, LinkButton, Notice, PageHeader, ProgressBar } from '../../shared/ui'
import { formatDate } from '../../shared/lib/format'
import { useSeriesId } from '../series/api'
import { usePipeline } from './api'
import { isRunActive, stageStates } from './stages'

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
      {active && <p className="muted">This page updates by itself. Long stories can take several minutes.</p>}
    </div>
  )
}
