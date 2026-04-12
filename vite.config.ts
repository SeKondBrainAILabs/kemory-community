/// <reference types="vitest" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    css: false,
  },
  server: {
    port: 3000,
    host: '0.0.0.0',
    proxy: {
      '/api': {
        target: 'http://localhost:8100',
        changeOrigin: true,
      },
      '/health': {
        target: 'http://localhost:8100',
        changeOrigin: true,
      },
      '/mcp': {
        target: 'http://localhost:8100',
        changeOrigin: true,
      },
      '/auth': {
        target: 'http://localhost:8888',
        changeOrigin: true,
      },
    },
  },
})
