import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { api, clearTokens, getAccessToken, setAccessToken, SESSION_EXPIRED_EVENT, tryRefresh } from '../api/client'
import type { CurrentUser } from '../types/api'
import { AuthContext } from './auth'

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<CurrentUser | null>(null)
  const [loading, setLoading] = useState(true)

  const loadCurrentUser = useCallback(async () => {
    // No token in memory after a reload: try to restore the session from the HttpOnly cookie.
    if (!getAccessToken() && !(await tryRefresh())) {
      setUser(null)
      setLoading(false)
      return
    }
    try {
      const me = await api.auth.me()
      setUser(me)
    } catch {
      clearTokens()
      setUser(null)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadCurrentUser()
  }, [loadCurrentUser])

  useEffect(() => {
    const onExpired = () => setUser(null)
    window.addEventListener(SESSION_EXPIRED_EVENT, onExpired)
    return () => window.removeEventListener(SESSION_EXPIRED_EVENT, onExpired)
  }, [])

  const login = useCallback(async (usernameOrEmail: string, password: string) => {
    const tokens = await api.auth.login(usernameOrEmail, password)
    setAccessToken(tokens.access_token)
    const me = await api.auth.me()
    setUser(me)
  }, [])

  const exploreDemo = useCallback(async () => {
    const tokens = await api.auth.demoSession()
    setAccessToken(tokens.access_token)
    const me = await api.auth.me()
    setUser(me)
  }, [])

  const logout = useCallback(() => {
    clearTokens()
    setUser(null)
    api.auth.logout().catch(() => undefined) // best effort: clear the refresh cookie on the server
  }, [])

  return <AuthContext.Provider value={{ user, loading, login, exploreDemo, logout }}>{children}</AuthContext.Provider>
}
