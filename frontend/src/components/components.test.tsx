import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import { DataOriginBadge } from './ui/Primitives'
import { ErrorBoundary } from './ErrorBoundary'

const authState = vi.hoisted(() => ({ role: 'viewer' as string | undefined }))
vi.mock('../context/auth', () => ({
  useAuth: () => ({ user: authState.role ? { role: authState.role } : null }),
}))
// Imported after the mock is registered (vi.mock is hoisted).
import { AdminOnly } from './AdminOnly'

afterEach(cleanup)

describe('DataOriginBadge', () => {
  it.each([
    ['synthetic_demo', 'synthetic demo'],
    ['user_upload', 'file upload'],
    ['external_source', 'external source'],
  ])('labels %s as "%s"', (origin, label) => {
    render(<DataOriginBadge origin={origin} />)
    expect(screen.getByText(label)).toBeTruthy()
  })

  it('never calls uploaded or connector data "real"', () => {
    for (const origin of ['user_upload', 'external_source']) {
      const { container, unmount } = render(<DataOriginBadge origin={origin} />)
      expect(container.textContent?.toLowerCase()).not.toContain('real')
      expect(container.querySelector('span')?.getAttribute('title')?.toLowerCase()).not.toContain('real')
      unmount()
    }
  })

  it('shows an unknown origin as readable text instead of guessing', () => {
    render(<DataOriginBadge origin="partner_feed" />)
    expect(screen.getByText('partner feed')).toBeTruthy()
  })
})

describe('AdminOnly', () => {
  it('renders the page for administrators', () => {
    authState.role = 'administrator'
    render(<AdminOnly><p>secret settings</p></AdminOnly>)
    expect(screen.getByText('secret settings')).toBeTruthy()
  })

  it.each(['analyst', 'investigator', 'viewer'])('shows a notice, not the page, to %s', (role) => {
    authState.role = role
    render(<AdminOnly><p>secret settings</p></AdminOnly>)
    expect(screen.queryByText('secret settings')).toBeNull()
    expect(screen.getByText('Administrators only')).toBeTruthy()
    expect(screen.getByText(new RegExp(`Your role \\(${role}\\)`))).toBeTruthy()
  })
})

describe('ErrorBoundary', () => {
  function Boom(): never {
    throw new Error('render failed')
  }

  it('contains a render crash and shows an alert', () => {
    vi.spyOn(console, 'error').mockImplementation(() => {}) // React logs the caught error
    render(
      <ErrorBoundary>
        <Boom />
      </ErrorBoundary>,
    )
    expect(screen.getByRole('alert')).toBeTruthy()
  })

  it('recovers when the reset key changes', () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    const { rerender } = render(
      <ErrorBoundary resetKey="/a">
        <Boom />
      </ErrorBoundary>,
    )
    rerender(
      <ErrorBoundary resetKey="/b">
        <p>next page</p>
      </ErrorBoundary>,
    )
    expect(screen.getByText('next page')).toBeTruthy()
  })
})
