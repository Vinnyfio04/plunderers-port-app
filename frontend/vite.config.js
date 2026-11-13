import { defineConfig } from 'vite'

const backend = process.env.VITE_BACKEND_URL || 'http://127.0.0.1:8000'

export default defineConfig({
  server: {
    proxy: {
      '/api': {
        target: backend,
        changeOrigin: true,
      },
      '/ws': {
        target: backend.replace(/^http/, 'ws'),
        ws: true,
      },
    },
  },
})
