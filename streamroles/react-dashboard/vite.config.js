import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  base: '/dashboard/',
  build: {
    outDir: '../static/react-build',
    emptyOutDir: true,
  },
  server: {
    proxy: {
      '/dashboard/proxy': {
        target: 'http://localhost:8080',
        changeOrigin: true,
      }
    }
  }
})
