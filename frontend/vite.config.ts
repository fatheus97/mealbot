import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  // Same-origin in dev: vite proxies /api/* to the backend so the browser
  // sees one origin (http://localhost:5173). Cookies stay SameSite=Lax,
  // matching the prod Caddy topology — no SameSite=None / HTTPS-in-dev
  // gymnastics. Override VITE_PROXY_TARGET when running outside compose
  // (e.g. `npm run dev` on the host: VITE_PROXY_TARGET=http://localhost:8000).
  const proxyTarget = env.VITE_PROXY_TARGET || 'http://backend:8000'

  return {
    plugins: [react()],
    server: {
      host: true, // Binds to 0.0.0.0 so the host can access it
      port: 5173,
      strictPort: true,
      watch: {
        usePolling: true, // Mandatory for Windows volume mounts
      },
      proxy: {
        '/api': {
          target: proxyTarget,
          changeOrigin: true,
        },
      },
    },
  }
})
