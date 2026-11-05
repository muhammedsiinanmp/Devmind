import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

// Django origin for the dev proxy. Compose sets this to http://django:8000;
// on the host it defaults to localhost.
const proxyTarget = process.env.API_PROXY_TARGET ?? 'http://localhost:8000'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      '/api': {
        target: proxyTarget,
        changeOrigin: true,
      },
    },
  },
})
