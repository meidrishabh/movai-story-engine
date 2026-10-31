import { Link } from 'react-router-dom'

import { Badge, Button, Card, ErrorNote, Loading } from '../../shared/ui'
import { plural } from '../../shared/lib/format'
import { useGenerationOverview, useSeriesPause } from './generationApi'

const money = (n: number) => n.toFixed(2)

/** Spend so far, each episode's budget and the pause switch for everything generated for the series. */
export default function GenerationPanel({ seriesId }: { seriesId: string }) {
  const overview = useGenerationOverview(seriesId)
  const pause = useSeriesPause(seriesId)

  if (overview.isPending) return <Loading />
  if (overview.isError) return <ErrorNote error={overview.error} onRetry={() => void overview.refetch()} />
  const data = overview.data
  const providers = Object.entries(data.providers).map(([kind, name]) => `${kind}: ${name}`).join(' · ')

  return (
    <Card>
      <div className="row row-between">
        <h2>Generation</h2>
        <div className="row">
          {data.paused && <Badge tone="warn">Paused</Badge>}
          <Button
            variant={data.paused ? 'primary' : 'secondary'}
            busy={pause.isPending}
            onClick={() => pause.mutate(!data.paused)}
          >
            {data.paused ? 'Resume generation' : 'Pause generation'}
          </Button>
        </div>
      </div>
      <p className="muted">
        {plural(data.requests, 'request')} so far, spent {money(data.spend)}
        {data.held > 0 && ` · ${data.held} held`}
        {data.awaiting_input > 0 && ` · ${data.awaiting_input} waiting for a result`} · {providers}
      </p>
      {data.episodes.length > 0 && (
        <table className="table">
          <thead>
            <tr>
              <th>Episode</th>
              <th>Requests</th>
              <th>Spent</th>
              <th>Cost cap</th>
              <th>Retries per shot</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {data.episodes.map((episode) => (
              <tr key={episode.episode_id}>
                <td>
                  <Link to={`../video/${episode.episode_id}`}>
                    {episode.episode_number}. {episode.title}
                  </Link>
                </td>
                <td>
                  {episode.requests}
                  {episode.failed > 0 && <> · <Badge tone="bad">{episode.failed} failed</Badge></>}
                  {episode.open > 0 && <> · {episode.open} open</>}
                </td>
                <td>{money(episode.spend)}</td>
                <td>{episode.budget.max_cost === null ? 'No cap' : money(episode.budget.max_cost)}</td>
                <td>{episode.budget.max_retries_per_shot}</td>
                <td>
                  {episode.budget.paused && <Badge tone="warn">Paused</Badge>}
                  {episode.budget.over_cost && <Badge tone="bad">Over cap</Badge>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Card>
  )
}
