import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

const login = vi.hoisted(() => vi.fn(() => Promise.resolve()))
vi.mock('../context/auth', () => ({
  useAuth: () => ({ user: null, loading: false, login, logout: () => undefined }),
}))
import { LoginPage } from './LoginPage'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  login.mockClear()
})

function stubDemo(body: unknown) {
  vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(new Response(JSON.stringify(body), { status: 200 }))))
}

const renderPage = () => render(<MemoryRouter><LoginPage /></MemoryRouter>)

describe('LoginPage demo accounts', () => {
  it('offers one-click sign-in for each shared account in a public demo', async () => {
    stubDemo({ enabled: true, password: 'Shared-Pass-1!', reset_hours: 6, // pragma: allowlist secret
               accounts: [{ username: 'admin', role: 'administrator' }, { username: 'viewer', role: 'viewer' }] })
    renderPage()
    const viewer = await screen.findByRole('button', { name: /viewer/i })
    expect(screen.getByText(/resets every 6 h/)).toBeTruthy()
    fireEvent.click(viewer)
    await waitFor(() => expect(login).toHaveBeenCalledWith('viewer', 'Shared-Pass-1!'))
  })

  it('shows no demo panel and no password when the deployment is not a demo', async () => {
    stubDemo({ enabled: false })
    const { container } = renderPage()
    await waitFor(() => expect(fetch).toHaveBeenCalled())
    expect(screen.queryByText(/Public demo/)).toBeNull()
    expect(container.textContent).not.toContain('DevPassword')
  })
})
