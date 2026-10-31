import { Suspense } from 'react'
import { NavLink, Outlet } from 'react-router-dom'

import { Loading } from '../../shared/ui'
import { useSeries, useSeriesId } from '../../features/series/api'

/** Steps in story order. `ready: true` items are on the roadmap and shown, but not clickable yet. */
const STEPS = [
  { to: 'upload', label: 'Upload', ready: true },
  { to: 'pipeline', label: 'Pipeline', ready: true },
  { to: 'characters', label: 'Characters & places', ready: true },
  { to: 'structure', label: 'Story structure', ready: true },
  { to: 'adaptation', label: 'Adaptation', ready: true },
  { to: 'plans', label: 'Episode plans', ready: true },
  { to: 'breakdown', label: 'Episode breakdown', ready: true },
  { to: 'style', label: 'Style bible', ready: true },
  { to: 'keyframes', label: 'Keyframes', ready: true },
] as const

export function SeriesLayout() {
  const seriesId = useSeriesId()
  const series = useSeries(seriesId)

  return (
    <div className="workspace">
      <aside className="sidebar">
        <div className="sidebar-title">
          <strong>{series.data?.title ?? '…'}</strong>
          {series.data?.genre && <span className="muted">{series.data.genre}</span>}
        </div>
        <nav aria-label="Series steps" className="stack" style={{ gap: 2 }}>
          {STEPS.map((step, index) =>
            step.ready ? (
              <NavLink key={step.to} to={step.to} className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}>
                <span className="nav-step">{index + 1}</span>
                {step.label}
              </NavLink>
            ) : (
              <span key={step.to} className="nav-link" aria-disabled="true" style={{ opacity: 0.5, cursor: 'default' }}>
                <span className="nav-step">{index + 1}</span>
                {step.label}
                <span className="nav-soon">soon</span>
              </span>
            ),
          )}
        </nav>
      </aside>
      <div>
        <Suspense fallback={<Loading />}>
          <Outlet />
        </Suspense>
      </div>
    </div>
  )
}
