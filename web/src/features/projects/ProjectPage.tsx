import { useState, type FormEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'

import { Badge, Button, Card, Empty, ErrorNote, Field, Loading, PageHeader } from '../../shared/ui'
import { plural } from '../../shared/lib/format'
import { useCreateSeries, useProject, useProjectSeries } from './api'

// The genre picks a story profile (what to protect when cutting filler), so offer the known ones.
const GENRES = ['mystery', 'romance', 'fantasy', 'science fiction', 'horror', 'comedy', 'adventure', 'drama']

export default function ProjectPage() {
  const { projectId = '' } = useParams()
  const navigate = useNavigate()
  const project = useProject(projectId)
  const series = useProjectSeries(projectId)
  const create = useCreateSeries(projectId)
  const [title, setTitle] = useState('')
  const [genre, setGenre] = useState('')

  function submit(event: FormEvent) {
    event.preventDefault()
    create.mutate(
      { title: title.trim(), genre: genre.trim() || undefined },
      { onSuccess: (created) => navigate(`/series/${created.id}/upload`) },
    )
  }

  if (project.isPending) return <Loading />
  if (project.isError) return <div className="page"><ErrorNote error={project.error} /></div>

  return (
    <div className="page">
      <PageHeader title={project.data.title} subtitle={project.data.description} />

      <Card>
        <h2>New series</h2>
        <form className="form" onSubmit={submit}>
          <Field label="Title">
            <input value={title} onChange={(e) => setTitle(e.target.value)} required maxLength={200} />
          </Field>
          <Field label="Genre" hint="Used to decide what counts as filler for this kind of story.">
            <input value={genre} onChange={(e) => setGenre(e.target.value)} list="genres" />
            <datalist id="genres">
              {GENRES.map((g) => (
                <option key={g} value={g} />
              ))}
            </datalist>
          </Field>
          <div className="row">
            <Button type="submit" variant="primary" busy={create.isPending} disabled={!title.trim()}>
              Create series
            </Button>
          </div>
          {create.isError && <ErrorNote error={create.error} />}
        </form>
      </Card>

      {series.isPending && <Loading />}
      {series.isError && <ErrorNote error={series.error} onRetry={() => void series.refetch()} />}
      {series.data && series.data.items.length === 0 && <Empty title="No series yet">Create one above, then upload the story.</Empty>}
      {series.data && series.data.items.length > 0 && (
        <div className="grid">
          {series.data.items.map((item) => (
            <Link key={item.id} to={`/series/${item.id}`} className="card" style={{ color: 'inherit' }}>
              <div className="row row-between">
                <h2>{item.title}</h2>
                {item.genre && <Badge tone="accent">{item.genre}</Badge>}
              </div>
              <p className="muted">{plural(item.episode_count ?? 0, 'episode')}</p>
            </Link>
          ))}
        </div>
      )}
    </div>
  )
}
