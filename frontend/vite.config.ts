import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      // Dev backend runs on :8001 so it doesn't collide with the always-on
      // launch agent serving the built app on :8000.
      '/api': 'http://localhost:8001',
    },
  },
})
