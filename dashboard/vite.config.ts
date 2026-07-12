import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig(({ command }) => ({
  plugins: [react()],
  // GitHub Pages serves the production build as a project page at
  // /forex-trading-ai/, not from the domain root - asset URLs need this
  // prefix there. Dev server stays at the plain root; Vite applies `base`
  // to both by default, which is what put /forex-trading-ai/ in the local
  // dev URL.
  base: command === "build" ? "/forex-trading-ai/" : "/",
}))
