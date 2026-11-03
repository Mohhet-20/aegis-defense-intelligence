// Content-Security-Policy helpers shared by the Docker build (render-nginx.mjs)
// and the Vite preview server (vite.config.ts), so the policy that is browser-
// tested with `npm run preview` is byte-for-byte the one nginx serves.
//
// The policy itself lives in ../nginx.conf (the deployed artifact). Its only
// variable part is the map tile origin, which comes from the same
// VITE_MAP_TILE_URL that is baked into the bundle.

import { readFileSync } from 'node:fs'

export const TILE_PLACEHOLDER = '__AEGIS_MAP_TILE_ORIGIN__'

/**
 * Origin to allow in img-src for a Leaflet tile URL template, or '' when no tiles
 * are configured. `{s}` subdomain templates become a `*.` wildcard.
 * Throws on anything that is not an http(s) URL, so a typo fails the build
 * instead of silently producing a broken or over-broad policy.
 */
export function tileOrigin(tileUrl) {
  const url = (tileUrl ?? '').trim()
  if (!url) return ''
  const m = /^(https?):\/\/([^/?#]+)/i.exec(url)
  if (!m) throw new Error(`VITE_MAP_TILE_URL must start with http:// or https:// (got ${JSON.stringify(url)})`)
  const host = m[2].replace(/^\{s\}\./, '*.')
  if (/[{}\s;,'"]/.test(host)) throw new Error(`Unsupported template in map tile host: ${JSON.stringify(m[2])}`)
  return `${m[1].toLowerCase()}://${host.toLowerCase()}`
}

/** nginx.conf text with the tile origin filled in. */
export function renderNginx(conf, tileUrl) {
  if (!conf.includes(TILE_PLACEHOLDER)) throw new Error('nginx.conf has no CSP tile placeholder')
  const origin = tileOrigin(tileUrl)
  // No tiles configured: drop the placeholder together with its leading space.
  return origin ? conf.split(TILE_PLACEHOLDER).join(origin) : conf.split(' ' + TILE_PLACEHOLDER).join('')
}

/** The CSP value from (rendered) nginx.conf, whitespace-normalized. */
export function cspFromNginx(conf) {
  const m = /add_header\s+Content-Security-Policy\s+"([^"]+)"/.exec(conf)
  if (!m) throw new Error('nginx.conf has no Content-Security-Policy header')
  return m[1].replace(/\s+/g, ' ').trim()
}

/** CSP for `vite preview`: read from nginx.conf (path relative to the working directory). */
export function previewCsp(nginxConfPath, tileUrl) {
  return cspFromNginx(renderNginx(readFileSync(nginxConfPath, 'utf8'), tileUrl))
}
