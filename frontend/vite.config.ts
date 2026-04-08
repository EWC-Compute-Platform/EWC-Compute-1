import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  test: {
    globals: true,
    environment: 'jsdom',
    // inside defineConfig({...}), add:
  test: {
    environment: "node",
    passWithNoTests: true,
  },
})

