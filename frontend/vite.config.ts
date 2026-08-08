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
      //
      // 127.0.0.1 rather than localhost, and overridable. On a host that
      // prefers IPv6 — Windows and macOS both do — `localhost` resolves to ::1
      // first, and Node tries addresses in that order without falling back, so
      // a v4-only API bound to 127.0.0.1 is simply unreachable and every
      // request through the proxy fails with an empty response. curl hides the
      // problem by trying both families.
      //
      // The override exists for Compose, where the API is another container and
      // this process's own loopback has nothing on port 8000.
      '/api': {
        target: process.env.VITE_PROXY_TARGET ?? 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
