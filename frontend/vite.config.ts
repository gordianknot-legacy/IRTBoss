import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'node:path'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { '@': path.resolve(__dirname, './src') },
  },
  server: {
    // 5173 is Vite's default and is what the backend's CORS allowlist and the
    // compose file both expect. Changing it means changing those too.
    port: 5173,
    proxy: {
      // The session is an HttpOnly cookie on the API's origin. Proxying in dev
      // keeps the browser on one origin so the cookie is sent without any
      // SameSite=None relaxation.
      '/api': { target: 'http://localhost:8000', changeOrigin: true },
    },
  },
})
