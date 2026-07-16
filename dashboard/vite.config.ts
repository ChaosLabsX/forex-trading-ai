import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: 'autoUpdate',
      includeAssets: ['favicon.ico', 'favicon-96x96.png', 'apple-touch-icon.png'],
      // The install name is the app's own identity ("Forex AI"). The DESCRIPTION
      // deliberately names no broker or platform: Safe Browsing reads phishing
      // as impersonation, and the flagged pattern was a specific broker's name
      // ("MT5 + IC Markets") beside a credential form. The manifest is fetchable
      // from the public login gate, so it stays broker-free even though the
      // signed-in app is branded. See docs/dashboard.md.
      manifest: {
        name: 'Forex AI',
        short_name: 'Forex AI',
        description: 'Private dashboard for one person\'s quantitative research project.',
        theme_color: '#0d0d0d',
        background_color: '#0d0d0d',
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
  // Served from a GitHub Pages CUSTOM DOMAIN (forex-automation.chaoslabsx.com,
  // set by public/CNAME), which serves at the domain ROOT - so base is "/", not
  // a "/<repo>/" project-page prefix. If this ever reverts to the bare
  // chaoslabsx.github.io/<repo>/ URL, base must become "/<repo>/" again or every
  // asset 404s and the page renders blank.
  base: "/",
})
