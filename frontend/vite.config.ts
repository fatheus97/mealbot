import { resolve } from 'node:path'
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
    build: {
      rollupOptions: {
        // Seven-page build: index.html (the static marketing landing at `/`)
        // and cs/index.html (its Czech twin at /cs); app.html (the SPA's own
        // namespace at /app, nginx-routed — see nginx.conf); and the legal
        // pages in both languages at /privacy, /terms, /cs/privacy and
        // /cs/terms. Keeps one image/nginx/CSP instead of a second service.
        //
        // The `cs` entry is NESTED on purpose: rollup preserves an input's
        // path relative to the project root, so this emits dist/cs/index.html
        // and nginx can serve /cs without a rewrite. A flat `cs.html` would
        // have needed one.
        input: {
          main: resolve(import.meta.dirname, 'index.html'),
          app: resolve(import.meta.dirname, 'app.html'),
          cs: resolve(import.meta.dirname, 'cs/index.html'),
          csPrivacy: resolve(import.meta.dirname, 'cs/privacy.html'),
          csTerms: resolve(import.meta.dirname, 'cs/terms.html'),
          privacy: resolve(import.meta.dirname, 'privacy.html'),
          terms: resolve(import.meta.dirname, 'terms.html'),
        },
      },
    },
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
