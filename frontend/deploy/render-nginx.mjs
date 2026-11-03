// Docker build step: write nginx.conf with the CSP's map tile origin filled in.
//   node deploy/render-nginx.mjs nginx.conf /tmp/default.conf   (reads VITE_MAP_TILE_URL)
import { readFileSync, writeFileSync } from 'node:fs'
import { cspFromNginx, renderNginx } from './csp.mjs'

const [src, dest] = process.argv.slice(2)
if (!src || !dest) {
  console.error('usage: node deploy/render-nginx.mjs <nginx.conf> <output>')
  process.exit(2)
}
const rendered = renderNginx(readFileSync(src, 'utf8'), process.env.VITE_MAP_TILE_URL)
writeFileSync(dest, rendered)
console.log(`CSP: ${cspFromNginx(rendered)}`)
