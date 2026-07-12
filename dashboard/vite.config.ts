import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  // GitHub Pages serves this as a project page at /forex-trading-ai/, not
  // from the domain root - asset URLs need this prefix to resolve.
  base: "/forex-trading-ai/",
})
