import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    host: true, // Binds to 0.0.0.0 so the host can access it
    port: 5173,
    strictPort: true,
    watch: {
      usePolling: true, // Mandatory for Windows volume mounts
    }
  }
})