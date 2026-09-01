import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    pool: 'threads',
    maxWorkers: 1,
    setupFiles: ['./src/test-setup.ts'],
    restoreMocks: true,
  },
})
