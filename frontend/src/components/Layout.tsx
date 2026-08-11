import { Link, Outlet, useLocation } from 'react-router-dom'

import { useCurrentUser, useLogout } from '@/api/hooks'
import { Button } from './ui'

export function Layout() {
  const { data: user } = useCurrentUser()
  const logout = useLogout()
  const location = useLocation()

  return (
    <div className="min-h-screen bg-canvas">
      <header className="sticky top-0 z-10 border-b border-rule bg-surface/95 backdrop-blur">
        <div className="mx-auto flex max-w-page items-center justify-between gap-4 px-5 py-3">
          <div className="flex items-baseline gap-4">
            <Link to="/projects" className="font-display text-title tracking-tight text-ink">
              IRTBoss
            </Link>
            <p className="hidden max-w-prose text-small text-ink-muted sm:block">
              Fit the models. Read the dossier. See what could not be computed.
            </p>
          </div>
          <div className="flex items-center gap-3">
            {user != null && (
              <span className="hidden text-small text-ink-muted sm:inline">{user.email}</span>
            )}
            <Button
              variant="secondary"
              onClick={() => logout.mutate()}
              disabled={logout.isPending}
            >
              Sign out
            </Button>
          </div>
        </div>
      </header>

      <main key={location.pathname} className="mx-auto max-w-page px-5 py-6">
        <Outlet />
      </main>

      <footer className="mx-auto max-w-page px-5 pb-8 pt-4">
        <p className="max-w-prose text-small text-ink-faint">
          Every statistic in this product is reported with what it could not
          establish. A blank is never a result — where a number is missing you
          will see “not computed” and, wherever the analysis recorded one, the
          reason.
        </p>
      </footer>
    </div>
  )
}
