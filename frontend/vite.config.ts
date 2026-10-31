import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The UI calls the API at /api. In dev, Vite forwards those calls to FastAPI.
// In production, FastAPI serves the built files from frontend/dist itself.
const apiTarget = process.env.API_URL ?? 'http://localhost:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { '/api': { target: apiTarget, changeOrigin: true } },
  },
  // The graph library (d3) and markdown renderer make one ~600 kB bundle; fine for a local app.
  build: { chunkSizeWarningLimit: 1000 },
})
