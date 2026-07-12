# Dashboard

React + TypeScript SPA (Vite), deployed to GitHub Pages via GitHub Actions.
Read-only monitoring (signals, open trades, trade history, engine health) is
public, using the Supabase anon key - RLS policies are the real access
boundary, not key secrecy (see [`../docs/architecture.md`](../docs/architecture.md)).
Pause/resume/emergency-close-all require signing in (Supabase Auth) and write
to the `commands` table, which the engine polls every couple of seconds.

## Local development

```
npm install
cp .env.example .env   # fill in VITE_SUPABASE_URL / VITE_SUPABASE_ANON_KEY
npm run dev
```

## Deployment

`.github/workflows/deploy-dashboard.yml` builds and deploys on every push to
`main` that touches `dashboard/**`. Requires the repo's Pages source (Settings
→ Pages → Build and deployment) to be set to **GitHub Actions**.
