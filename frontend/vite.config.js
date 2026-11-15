import { defineConfig } from 'vite'
import { Agent } from 'node:http'

const backend = process.env.VITE_BACKEND_URL || 'http://127.0.0.1:8000'

export default defineConfig({
  server: {
    proxy: {
      '/api': {
        target: backend,
        changeOrigin: true,
        // FastAPI's streaming middleware needs the connection kept open until the body drains.
        agent: new Agent({ keepAlive: true }),
      },
      '/ws': {
        target: backend.replace(/^http/, 'ws'),
        ws: true,
      },
    },
  },
})
