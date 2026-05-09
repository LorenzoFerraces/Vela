import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    allowedHosts: ['velaunq.ddns.net'],
    proxy: {
      // HTTP + WebSocket (container log stream) to FastAPI. Same-origin /api avoids
      // mixed-content blocking of ws: from an https:// dev page.
      '/api': {
        target: process.env.VITE_DEV_PROXY_TARGET ?? 'http://127.0.0.1:8000',
        changeOrigin: true,
        secure: false,
        ws: true,
      },
    },
  },
})
