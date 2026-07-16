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
      // Naming here is a SAFETY surface, not branding. Google Safe Browsing
      // flagged chaoslabsx.github.io as social engineering, and its definition
      // of phishing is impersonation ("sites that pretend to be other sites").
      // A credential form captioned with a broker's name on free shared hosting
      // is that pattern exactly, so no broker or platform name appears on any
      // public-facing string. "Strategy Lab" is also just the honest
      // description - see docs/strategy-lab.md.
      manifest: {
        name: 'Strategy Lab',
        short_name: 'Strategy Lab',
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
  // Served from a GitHub Pages CUSTOM DOMAIN (second-automation.chaoslabsx.com,
  // set by public/CNAME), which serves at the domain ROOT - so base is "/", not
  // a "/<repo>/" project-page prefix. If this ever reverts to the bare
  // chaoslabsx.github.io/<repo>/ URL, base must become "/<repo>/" again or every
  // asset 404s and the page renders blank.
  base: "/",
})
