import { lazy } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'

import { Empty } from '../shared/ui'
import { AppShell } from './layouts/AppShell'
import { SeriesLayout } from './layouts/SeriesLayout'

// Each screen is its own chunk, so a new feature adds a route here and nothing else.
const ProjectsPage = lazy(() => import('../features/projects/ProjectsPage'))
const ProjectPage = lazy(() => import('../features/projects/ProjectPage'))
const UploadPage = lazy(() => import('../features/series/UploadPage'))
const PipelinePage = lazy(() => import('../features/pipeline/PipelinePage'))
const AdaptationPage = lazy(() => import('../features/adaptation/AdaptationPage'))
const PlansPage = lazy(() => import('../features/plans/PlansPage'))
const CharactersPage = lazy(() => import('../features/characters/CharactersPage'))
const StructurePage = lazy(() => import('../features/structure/StructurePage'))
const BreakdownPage = lazy(() => import('../features/breakdown/BreakdownPage'))
const StylePage = lazy(() => import('../features/style/StylePage'))
const VoicesPage = lazy(() => import('../features/sound/VoicesPage'))
const SoundPage = lazy(() => import('../features/sound/SoundPage'))

export function AppRoutes() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<ProjectsPage />} />
        <Route path="projects/:projectId" element={<ProjectPage />} />
        <Route path="series/:seriesId" element={<SeriesLayout />}>
          <Route index element={<Navigate to="upload" replace />} />
          <Route path="upload" element={<UploadPage />} />
          <Route path="pipeline" element={<PipelinePage />} />
          <Route path="characters" element={<CharactersPage />} />
          <Route path="structure" element={<StructurePage />} />
          <Route path="adaptation" element={<AdaptationPage />} />
          <Route path="plans" element={<PlansPage />} />
          <Route path="breakdown" element={<BreakdownPage />} />
          <Route path="style" element={<StylePage />} />
          <Route path="voices" element={<VoicesPage />} />
          <Route path="sound" element={<SoundPage />} />
          <Route path="*" element={<div className="page"><Empty title="Page not found">That step does not exist.</Empty></div>} />
        </Route>
        <Route path="*" element={<div className="page"><Empty title="Page not found">Check the address, or go back to the projects list.</Empty></div>} />
      </Route>
    </Routes>
  )
}
