import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  build: {
    chunkSizeWarningLimit: 900,
    rollupOptions: {
      output: { manualChunks: { echarts: ['echarts/core', 'echarts/charts', 'echarts/components', 'echarts/renderers'] } },
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': { target: process.env.VITE_API_TARGET || 'http://localhost:8000', changeOrigin: true },
    },
  },
})
