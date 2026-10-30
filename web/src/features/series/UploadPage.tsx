import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'

import { Badge, Button, Card, ErrorNote, Field, Loading, Notice, PageHeader } from '../../shared/ui'
import { formatDate, formatMinutes } from '../../shared/lib/format'
import { usePipeline } from '../pipeline/api'
import { isRunActive } from '../pipeline/stages'
import { useAnalyze, useEstimate, useSeriesId, useUploadSource } from './api'

const ACCEPT = '.md,.markdown,.pdf'

export default function UploadPage() {
  const seriesId = useSeriesId()
  const navigate = useNavigate()
  const pipeline = usePipeline(seriesId)
  const source = pipeline.data?.source ?? null
  const estimate = useEstimate(seriesId, source !== null)
  const upload = useUploadSource(seriesId)
  const analyze = useAnalyze(seriesId)
  const [file, setFile] = useState<File | null>(null)
  const [title, setTitle] = useState('')

  const running = isRunActive(pipeline.data?.analysis_run)

  function submit(event: FormEvent) {
    event.preventDefault()
    if (!file) return
    upload.mutate({ file, title: title.trim() || file.name }, { onSuccess: () => setFile(null) })
  }

  function start() {
    analyze.mutate(undefined, { onSuccess: () => navigate('../pipeline') })
  }

  if (pipeline.isPending) return <Loading />
  if (pipeline.isError) return <div className="page"><ErrorNote error={pipeline.error} onRetry={() => void pipeline.refetch()} /></div>

  return (
    <div className="page">
      <PageHeader title="Upload story" subtitle="Markdown or text-layer PDF, up to 25 MB." />

      {source && (
        <Card>
          <div className="row row-between">
            <h2>{source.title}</h2>
            <Badge tone="ok">{source.validation_status}</Badge>
          </div>
          <p className="muted">
            {source.original_filename} · uploaded {formatDate(source.created_at)}
          </p>
          {estimate.data && (
            <p>
              <strong>{estimate.data.words.toLocaleString()}</strong> words in {estimate.data.chunks} chunks. The analysis makes about{' '}
              <strong>{estimate.data.llm_calls}</strong> model calls for entity extraction and takes at least{' '}
              {formatMinutes(estimate.data.minimum_seconds)}; the later stages add more.
            </p>
          )}
          {estimate.data && !estimate.data.within_call_limit && (
            <Notice tone="bad">
              This story needs more model calls than the limit of {estimate.data.max_calls_allowed}. Raise LLM_MAX_CALLS_PER_RUN to analyse it.
            </Notice>
          )}
          <div className="row">
            <Button variant="primary" onClick={start} busy={analyze.isPending} disabled={running || estimate.data?.within_call_limit === false}>
              {running ? 'Analysis is running' : pipeline.data.analysis_run ? 'Analyse again' : 'Analyse the story'}
            </Button>
          </div>
          {analyze.isError && <ErrorNote error={analyze.error} />}
        </Card>
      )}

      <Card>
        <h2>{source ? 'Replace the story' : 'Choose a file'}</h2>
        <form className="form" onSubmit={submit}>
          <Field label="File">
            <input type="file" accept={ACCEPT} onChange={(e) => setFile(e.target.files?.[0] ?? null)} required />
          </Field>
          <Field label="Title" hint="Defaults to the file name.">
            <input value={title} onChange={(e) => setTitle(e.target.value)} />
          </Field>
          <div className="row">
            <Button type="submit" variant={source ? 'secondary' : 'primary'} busy={upload.isPending} disabled={!file}>
              Upload
            </Button>
          </div>
          {upload.isError && <ErrorNote error={upload.error} />}
          {upload.isSuccess && <Notice>Uploaded and validated.</Notice>}
        </form>
      </Card>
    </div>
  )
}
