import { useState, type FormEvent } from 'react'
import { Navigate, useLocation } from 'react-router-dom'

import { ApiError } from '@/api/client'
import { useCurrentUser, useLogin, useRegister } from '@/api/hooks'
import { Button, Callout, Field, inputClass, Spinner } from '@/components/ui'

/** `MIN_PASSWORD_LENGTH` in `backend/app/auth/passwords.py` is enforced server-side. */
const MIN_PASSWORD_LENGTH = 12

type Mode = 'login' | 'register'

export function AuthPage() {
  const { data: user, isPending } = useCurrentUser()
  const location = useLocation()
  const [mode, setMode] = useState<Mode>('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')

  const login = useLogin()
  const register = useRegister()
  const active = mode === 'login' ? login : register

  if (isPending) {
    return (
      <div className="grid min-h-screen place-items-center">
        <Spinner label="Checking your session…" />
      </div>
    )
  }
  if (user != null) {
    const from = (location.state as { from?: string } | null)?.from
    return <Navigate to={from ?? '/projects'} replace />
  }

  function submit(event: FormEvent) {
    event.preventDefault()
    active.mutate({ email, password })
  }

  const error = active.error
  const detail =
    error instanceof ApiError
      ? error.detail
      : error != null
        ? (error as Error).message
        : null

  return (
    <div className="grid min-h-screen place-items-center bg-canvas px-5 py-8">
      <div className="w-full max-w-[26rem] space-y-5">
        <div>
          <h1 className="font-display text-display text-ink">IRTBoss</h1>
          <p className="mt-2 max-w-prose text-body text-ink-muted">
            Item response models, fitted and diagnosed. The report tells you what
            the data supports, what it does not, and which statistics could not be
            computed at all. It does not tell you which model won — that is not a
            question the evidence answers.
          </p>
        </div>

        <div className="rounded-lg border border-rule bg-surface p-5 shadow-card">
          <div className="mb-4 flex gap-1 rounded bg-sunken p-1">
            {(['login', 'register'] as const).map((m) => (
              <button
                key={m}
                type="button"
                onClick={() => setMode(m)}
                className={
                  'flex-1 rounded px-3 py-1 text-small font-semibold transition-colors ' +
                  (mode === m ? 'bg-surface text-ink shadow-card' : 'text-ink-muted')
                }
              >
                {m === 'login' ? 'Sign in' : 'Create account'}
              </button>
            ))}
          </div>

          <form onSubmit={submit} className="space-y-4">
            <Field label="Email" htmlFor="email">
              <input
                id="email"
                type="email"
                required
                autoComplete="username"
                className={inputClass}
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </Field>

            <Field
              label="Password"
              htmlFor="password"
              hint={
                mode === 'register'
                  ? `At least ${MIN_PASSWORD_LENGTH} characters.`
                  : undefined
              }
            >
              <input
                id="password"
                type="password"
                required
                minLength={mode === 'register' ? MIN_PASSWORD_LENGTH : undefined}
                autoComplete={mode === 'register' ? 'new-password' : 'current-password'}
                className={inputClass}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </Field>

            {detail != null && (
              <Callout tone="alarm" title="That did not work">
                {detail}
              </Callout>
            )}

            <Button type="submit" disabled={active.isPending} className="w-full">
              {active.isPending
                ? 'Working…'
                : mode === 'login'
                  ? 'Sign in'
                  : 'Create account'}
            </Button>
          </form>
        </div>

        <p className="text-small text-ink-faint">
          The session is an HttpOnly cookie set by the API. Nothing is stored in
          this browser’s local storage.
        </p>
      </div>
    </div>
  )
}
