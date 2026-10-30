import type { AnalysisRun } from './types'

/**
 * The analysis stages in order, each with the run progress (0-100) at which it is finished.
 * These mirror PROGRESS in backend/app/services/analysis_pipeline.py; add a stage here when the backend gains one.
 */
export const STAGES = [
  { key: 'chunk_analysis', label: 'Read the story', doneAt: 20 },
  { key: 'entity_extraction', label: 'Find characters, places and objects', doneAt: 85 },
  { key: 'timeline', label: 'Order the events', doneAt: 88 },
  { key: 'continuity', label: 'Track continuity and contradictions', doneAt: 92 },
  { key: 'master_script', label: 'Write the master script', doneAt: 95 },
  { key: 'adaptations', label: 'Look for filler', doneAt: 97 },
  { key: 'episode_plan', label: 'Plan the episodes', doneAt: 99 },
] as const

export type StageState = 'done' | 'active' | 'waiting' | 'failed'

export function stageStates(run: AnalysisRun | null): { key: string; label: string; state: StageState }[] {
  const progress = run?.progress ?? 0
  const finished = run?.status === 'succeeded'
  const failed = run?.status === 'failed'
  let activeFound = false
  return STAGES.map((stage) => {
    if (finished || progress >= stage.doneAt) return { key: stage.key, label: stage.label, state: 'done' as const }
    if (!activeFound && run) {
      activeFound = true
      return { key: stage.key, label: stage.label, state: failed ? ('failed' as const) : ('active' as const) }
    }
    return { key: stage.key, label: stage.label, state: 'waiting' as const }
  })
}

export const isRunActive = (run: AnalysisRun | null | undefined) => run?.status === 'queued' || run?.status === 'running'
