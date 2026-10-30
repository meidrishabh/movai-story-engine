import { Suspense } from 'react'
import { Link, Outlet } from 'react-router-dom'

import { Loading } from '../../shared/ui'

/** Top bar shared by every screen. */
export function AppShell() {
  return (
    <>
      <header className="shell-top">
        <Link to="/" className="brand">
          Mov<span>AI</span>
        </Link>
        <nav className="crumbs" aria-label="Breadcrumb">
          <Link to="/">Projects</Link>
        </nav>
      </header>
      <main>
        <Suspense fallback={<Loading />}>
          <Outlet />
        </Suspense>
      </main>
    </>
  )
}
