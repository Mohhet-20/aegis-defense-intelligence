import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import { previewCsp } from './deploy/csp.mjs'

// AEGIS frontend dev server. In development, API calls to /api/v1/*
// are proxied straight to the real FastAPI backend -- there is no mock
// server anywhere in this codebase (Rule 3). AEGIS_DEV_API_TARGET (from
// the shell or frontend/.env; dev/preview-server only, never bundled
// because it has no VITE_ prefix) points the proxy at another backend.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '.', ['AEGIS_DEV_', 'VITE_'])
  const proxy = {
    '/api': {
      target: env.AEGIS_DEV_API_TARGET || 'http://localhost:8000',
      changeOrigin: true,
    },
  }
  // `npm run preview` serves the production build with the same CSP as
  // nginx.conf, so the deployed policy can be browser-tested locally. Not on
  // the dev server: Vite's hot reload needs inline scripts.
  const csp = previewCsp('nginx.conf', env.VITE_MAP_TILE_URL)
  return {
    plugins: [react()],
    server: { port: 5173, proxy },
    preview: { proxy, headers: { 'Content-Security-Policy': csp } },
  }
})
