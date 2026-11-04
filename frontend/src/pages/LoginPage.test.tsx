import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

const login = vi.hoisted(() => vi.fn(() => Promise.resolve()))
const exploreDemo = vi.hoisted(() => vi.fn(() => Promise.resolve()))
vi.mock('../context/auth', () => ({
  useAuth: () => ({ user: null, loading: false, login, exploreDemo, logout: () => undefined }),
}))
import { LoginPage } from './LoginPage'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  login.mockClear()
  exploreDemo.mockClear()
})

function stubDemo(body: unknown) {
  vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(new Response(JSON.stringify(body), { status: 200 }))))
}

const renderPage = () => render(<MemoryRouter><LoginPage /></MemoryRouter>)

describe('LoginPage public demo', () => {
  it('offers a guest session without showing any account or password', async () => {
    stubDemo({ enabled: true, reset_hours: 6 })
    const { container } = renderPage()
    const explore = await screen.findByRole('button', { name: 'Explore the live demo' })
    expect(screen.getByText(/resets every 6 h/)).toBeTruthy()
    expect(container.textContent).not.toMatch(/passwords*[:=]|DevPassword/i)
    expect(screen.queryByRole('button', { name: /administrator/i })).toBeNull()
    fireEvent.click(explore)
    await waitFor(() => expect(exploreDemo).toHaveBeenCalledTimes(1))
    expect(login).not.toHaveBeenCalled()
  })

  it('shows no demo panel and no password when the deployment is not a demo', async () => {
    stubDemo({ enabled: false })
    const { container } = renderPage()
    await waitFor(() => expect(fetch).toHaveBeenCalled())
    expect(screen.queryByRole('button', { name: 'Explore the live demo' })).toBeNull()
    expect(container.textContent).not.toContain('DevPassword')
  })
})
