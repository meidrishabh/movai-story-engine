import { useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'

import { Button, Card, Empty, ErrorNote, Field, Loading, PageHeader, Badge } from '../../shared/ui'
import { plural } from '../../shared/lib/format'
import { useCreateProject, useProjects } from './api'

export default function ProjectsPage() {
  const projects = useProjects()
  const create = useCreateProject()
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')

  function submit(event: FormEvent) {
    event.preventDefault()
    create.mutate(
      { title: title.trim(), description: description.trim() || undefined },
      {
        onSuccess: () => {
          setTitle('')
          setDescription('')
        },
      },
    )
  }

  return (
    <div className="page">
      <PageHeader title="Projects" subtitle="Each project holds the series made from one story." />

      <Card>
        <h2>New project</h2>
        <form className="form" onSubmit={submit}>
          <Field label="Title">
            <input value={title} onChange={(e) => setTitle(e.target.value)} required maxLength={200} />
          </Field>
          <Field label="Description" hint="Optional">
            <input value={description} onChange={(e) => setDescription(e.target.value)} />
          </Field>
          <div className="row">
            <Button type="submit" variant="primary" busy={create.isPending} disabled={!title.trim()}>
              Create project
            </Button>
          </div>
          {create.isError && <ErrorNote error={create.error} />}
        </form>
      </Card>

      {projects.isPending && <Loading />}
      {projects.isError && <ErrorNote error={projects.error} onRetry={() => void projects.refetch()} />}
      {projects.data && projects.data.items.length === 0 && (
        <Empty title="No projects yet">Create one above to get started.</Empty>
      )}
      {projects.data && projects.data.items.length > 0 && (
        <div className="grid">
          {projects.data.items.map((project) => (
            <Link key={project.id} to={`/projects/${project.id}`} className="card" style={{ color: 'inherit' }}>
              <div className="row row-between">
                <h2>{project.title}</h2>
                <Badge>{plural(project.series_count, 'series', 'series')}</Badge>
              </div>
              {project.description && <p className="muted">{project.description}</p>}
            </Link>
          ))}
        </div>
      )}
    </div>
  )
}
