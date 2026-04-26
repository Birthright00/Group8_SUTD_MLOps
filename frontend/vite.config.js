import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import fs from 'fs'
import path from 'path'

// Read proxy port from .proxy-port file (written by proxy_server.py)
function getProxyPort() {
  const portFile = path.join(__dirname, '..', '.proxy-port')
  try {
    return parseInt(fs.readFileSync(portFile, 'utf-8').trim(), 10)
  } catch {
    console.warn('Warning: .proxy-port not found. Start proxy_server.py first.')
    return 4000  // fallback
  }
}

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: `http://localhost:${getProxyPort()}`,
        changeOrigin: true,
      }
    }
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
  }
})
