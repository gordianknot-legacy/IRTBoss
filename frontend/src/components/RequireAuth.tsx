import type { ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router-dom'

import { useCurrentUser } from '@/api/hooks'
import { Spinner } from './ui'

/**
 * The session lives in an HttpOnly cookie, so the only way to know whether one
 * exists is to ask the server. `useCurrentUser` turns a 401 into `null` rather
 * than an error, which is why the three states below are distinguishable.
 */
export function RequireAuth({ children }: { children: ReactNode }) {
  const { data: user, isPending, error } = useCurrentUser()
  const location = useLocation()

  if (isPending) {
    return (
      <div className="grid min-h-screen place-items-center">
        <Spinner label="Checking your session…" />
      </div>
    )
  }

  if (error != null) {
    return (
      <div className="mx-auto max-w-prose px-5 py-9">
        <h1 className="font-display text-title">Could not reach the API</h1>
        <p className="mt-2 text-body text-ink-muted">{(error as Error).message}</p>
      </div>
    )
  }

  if (user == null) {
    return <Navigate to="/sign-in" replace state={{ from: location.pathname }} />
  }

  return <>{children}</>
}
