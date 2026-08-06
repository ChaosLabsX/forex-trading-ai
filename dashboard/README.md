# Dashboard

React + TypeScript SPA (Vite), deployed to GitHub Pages via GitHub Actions.
Read-only monitoring (signals, open trades, trade history, engine health) is
public, using the Supabase anon key - RLS policies are the real access
boundary, not key secrecy. Pause/resume/emergency-close-all require signing in
(Supabase Auth) and write to the `commands` table, which the engine polls
every couple of seconds.

See [`../docs/dashboard.md`](../docs/dashboard.md) for the full structure/auth
model and [`../docs/architecture.md`](../docs/architecture.md) for how this
fits into the rest of the system.

## Local development

```
npm install
cp .env.example .env   # fill in VITE_SUPABASE_URL / VITE_SUPABASE_ANON_KEY
npm run dev
```

Then open the URL `npm run dev` prints (http://localhost:5173).

### Do not open `index.html` directly

`index.html` is Vite's **source entry**, not a page. Its last line is
`<script type="module" src="/src/main.tsx">`, and `main.tsx` is TypeScript +
JSX - no browser can execute it. Opening this file from VS Code's Live Server
(or a `file://` URL, or any other plain static server) gives a **white page**
and a console 404 for `/src/main.tsx`, because a static server has no build
step and hands the file over untouched. Nothing is broken; the file simply is
not the app.

The app only exists after Vite compiles it. Two ways to get it:

| You want | Do this | Open |
|---|---|---|
| To develop, with hot reload | `npm run dev` | http://localhost:5173 |
| A built copy served by any static server | `npm run build:static` | `dist/index.html` |

`build:static` is a normal production build with two changes, both required by
static hosting from a subfolder (see the comments in `vite.config.ts`):

- **`base: './'`** so the bundle asks for `./assets/...` relative to wherever
  the page sits. The deployed build uses `base: '/'` because GitHub Pages
  serves it from a custom domain root - and that build white-pages under a
  subfolder for its own reason, confirmed live: it requests
  `/assets/index-*.js`, `/registerSW.js` and `/manifest.webmanifest` at the
  server ROOT, gets an HTML 404 page back for each, and the stylesheet then
  fails a MIME check because an error page is not CSS.
- **the PWA/service worker is disabled**, which removes the `registerSW.js` and
  `manifest.webmanifest` requests entirely, and stops a cached app shell from
  making a rebuild look like it did nothing.

With Live Server rooted at the repo, that lands at:

```
http://127.0.0.1:5500/dashboard/dist/index.html
```

Re-run `npm run build:static` after every change - a static server serves the
last build, not your working tree. `npm run dev` exists precisely so you don't
have to. Note both builds write to the same `dist/`, so whichever you ran last
is what is there; deployment is unaffected either way, since CI runs its own
`npm run build` from a clean checkout.

## Deployment

`.github/workflows/deploy-dashboard.yml` builds and deploys on every push to
`main` that touches `dashboard/**`. Requires the repo's Pages source (Settings
→ Pages → Build and deployment) to be set to **GitHub Actions**.
