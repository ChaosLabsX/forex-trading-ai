import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'

// https://vite.dev/config/
export default defineConfig(({ command }) => ({
  plugins: [
    react(),
    VitePWA({
      registerType: 'autoUpdate',
      includeAssets: ['favicon.ico', 'favicon-96x96.png', 'apple-touch-icon.png'],
      manifest: {
        name: 'Forex AI',
        short_name: 'Forex AI',
        description: 'MT5 + IC Markets automated trading - monitoring and control',
        theme_color: '#14161c',
        background_color: '#14161c',
        display: 'standalone',
        start_url: '.',
        icons: [
          { src: 'pwa-192x192.png', sizes: '192x192', type: 'image/png', purpose: 'any' },
          { src: 'pwa-512x512.png', sizes: '512x512', type: 'image/png', purpose: 'any' },
          { src: 'pwa-192x192.png', sizes: '192x192', type: 'image/png', purpose: 'maskable' },
          { src: 'pwa-512x512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
        ],
      },
      workbox: {
        // Trading data must never be served stale from a cache - only the
        // app shell (JS/CSS/HTML/icons) gets precached. Supabase calls go to
        // a different origin and aren't touched by the service worker at all
        // since no runtimeCaching rule is defined for it here.
        globPatterns: ['**/*.{js,css,html,ico,png,svg,webmanifest}'],
      },
    }),
  ],
  // GitHub Pages serves the production build as a project page at
  // /forex-trading-ai/, not from the domain root - asset URLs need this
  // prefix there. Dev server stays at the plain root; Vite applies `base`
  // to both by default, which is what put /forex-trading-ai/ in the local
  // dev URL.
  base: command === "build" ? "/forex-trading-ai/" : "/",
}))
