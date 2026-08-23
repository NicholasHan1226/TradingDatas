import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// The build output is committed to ../static/app and served by Cloudflare
// Pages under the /app/ path alongside the legacy console in static/.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  base: '/app/',
  build: {
    outDir: '../static/app',
    emptyOutDir: true,
  },
})
