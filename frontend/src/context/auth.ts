import { createContext, useContext } from 'react'
import type { CurrentUser } from '../types/api'

// The auth context object and its hook live here (not in AuthContext.tsx) so that
// file exports only a component, which keeps React Fast Refresh working.

export interface AuthState {
  user: CurrentUser | null
  loading: boolean
  login: (usernameOrEmail: string, password: string) => Promise<void>
  /** Public demo only: a guest session as the analyst account, no password involved. */
  exploreDemo: () => Promise<void>
  logout: () => void
}

export const AuthContext = createContext<AuthState | null>(null)

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
