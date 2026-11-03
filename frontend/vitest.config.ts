import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

// Component and unit tests (`npm test`). Browser-level journeys live in
// backend/scripts/e2e_*.py and run against a real backend.
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    include: ['src/**/*.test.{ts,tsx}', 'deploy/**/*.test.mjs'],
    restoreMocks: true,
  },
})
