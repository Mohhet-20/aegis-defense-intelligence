// @vitest-environment node
import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'
import { cspFromNginx, renderNginx, tileOrigin, TILE_PLACEHOLDER } from './csp.mjs'

const conf = readFileSync(new URL('../nginx.conf', import.meta.url), 'utf8')
const allCsp = (text) => [...text.matchAll(/add_header\s+Content-Security-Policy\s+"([^"]+)"/g)].map((m) => m[1])

describe('tileOrigin', () => {
  it.each([
    ['', ''],
    [undefined, ''],
    ['https://tile.openstreetmap.org/{z}/{x}/{y}.png', 'https://tile.openstreetmap.org'],
    ['https://{s}.tile.example.org/{z}/{x}/{y}.png', 'https://*.tile.example.org'],
    ['HTTPS://Tiles.Example.org:8443/x/{z}/{x}/{y}', 'https://tiles.example.org:8443'],
  ])('%s -> %s', (url, origin) => {
    expect(tileOrigin(url)).toBe(origin)
  })

  it.each(['javascript:alert(1)', 'data:image/png;base64,AAAA', '//tiles.example.org/{z}', "https://a.org';script-src *"])(
    'rejects %s',
    (url) => {
      expect(() => tileOrigin(url)).toThrow()
    },
  )
})

describe('nginx.conf CSP', () => {
  it('is identical in every place nginx sets it', () => {
    const policies = allCsp(conf)
    expect(policies.length).toBeGreaterThanOrEqual(2)
    expect(new Set(policies).size).toBe(1)
  })

  it('allows no inline or eval script and no plugins or framing', () => {
    const csp = cspFromNginx(renderNginx(conf, ''))
    const script = /script-src ([^;]+)/.exec(csp)[1]
    expect(script.trim()).toBe("'self'")
    expect(csp).not.toContain('unsafe-inline')
    expect(csp).not.toContain('unsafe-eval')
    expect(csp).toContain("object-src 'none'")
    expect(csp).toContain("frame-ancestors 'none'")
    expect(csp).toContain("connect-src 'self'")
  })

  it('leaves no placeholder behind, with or without a tile host', () => {
    for (const url of ['', 'https://tile.openstreetmap.org/{z}/{x}/{y}.png']) {
      const rendered = renderNginx(conf, url)
      expect(rendered).not.toContain(TILE_PLACEHOLDER)
      expect(new Set(allCsp(rendered)).size).toBe(1)
    }
    expect(cspFromNginx(renderNginx(conf, ''))).toContain("img-src 'self' data: blob:;")
    expect(cspFromNginx(renderNginx(conf, 'https://tile.openstreetmap.org/{z}/{x}/{y}.png'))).toContain(
      "img-src 'self' data: blob: https://tile.openstreetmap.org;",
    )
  })
})
