/// <reference types="vitest" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'
import { readFileSync } from 'fs'

const pkg = JSON.parse(readFileSync('./package.json', 'utf-8'))

// FE_VERSION lets the SDDMini deploy workflow inject the release tag
// (stripped to bare semver, e.g. "3.37.4") so the dashboard's "FE:x.y.z"
// badge tracks the actual deployed tag instead of the long-stale
// package.json default. Falls back to package.json so local dev and
// CI/cloud builds without the env still get a sensible value.
const FE_VERSION = process.env.FE_VERSION || pkg.version

export default defineConfig({
  plugins: [react()],
  define: {
    __FE_VERSION__: JSON.stringify(FE_VERSION),
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    environmentOptions: {
      jsdom: { url: 'http://localhost:3000' },
    },
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
