# Dashboard

React + TypeScript SPA (Vite), in `dashboard/`. Deployed to GitHub Pages via
`.github/workflows/deploy-dashboard.yml` on every push to `main` touching
`dashboard/**`. See [`dashboard/README.md`](../dashboard/README.md) for local
setup commands.

## Structure

```
src/
  lib/
    supabase.ts    creates the Supabase client from VITE_SUPABASE_URL / VITE_SUPABASE_ANON_KEY
    useAuth.ts      hook: current session, signIn, signOut
  components/
    EngineHealth.tsx    latest heartbeat, staleness check (>3min = stale)
    OpenTrades.tsx       trades where status=OPEN
    TradeHistory.tsx     trades where status=CLOSED + win-rate/P&L stats
    SignalsFeed.tsx      recent signals, joined with ai_reviews
    Login.tsx            email/password sign-in form
    SetPassword.tsx      shown whenever signed in - needed once after an invite/reset link
    Controls.tsx         pause/resume/emergency-close-all buttons, shown when signed in
  types.ts          TS types mirroring the Supabase schema
App.tsx             wires it all together: EngineHealth always shown; Controls+SetPassword
                    when signed in, Login when not; monitoring views always shown
```

No routing library - it's one page. No state management library - each
component fetches its own slice of Supabase state with `useEffect` +
`setInterval` (15s poll; nothing here needs sub-second freshness).

## Auth model

- **Reading** signals/trades/heartbeats/candles/ai_reviews works with **no
  sign-in** - the anon key has `SELECT` granted via RLS policies (see
  `supabase/migrations/0005_phase4_dashboard_rls.sql` and
  `0007_authenticated_read_monitoring.sql`). This is deliberately public: it's
  a monitoring dashboard, and nothing in those tables is sensitive.
- **Writing** (pause/resume/emergency-close-all) requires being signed in.
  `Controls.tsx` inserts into `commands` with `created_by: session.user.id`;
  RLS only allows `authenticated` to insert, and only with
  `auth.uid() = created_by`.
- Public sign-up is **disabled** on the Supabase Auth project
  (`disable_signup: true`) - only one invited user exists. There's no
  "register" flow in the UI and there shouldn't be one added without
  reconsidering this model first.
- `SetPassword.tsx` exists because Supabase's invite/recovery links
  authenticate via a one-time token but never prompt for a password - without
  this component there was nowhere to actually set one after following an
  invite email.

**Important gotcha already hit once:** once a user is signed in, `supabase-js`
sends their session JWT on every request, not the anon key - so `authenticated`
needs its own grants/RLS policies on every table the dashboard reads, even the
"public" ones. Granting only `anon` (and forgetting `authenticated`) causes
403s for signed-in users specifically. See `docs/safety-rails.md`.

## Deployment

- `vite.config.ts`: `base` is `/forex-trading-ai/` for the production build
  (GitHub Pages serves this repo as a project page at that path) and `/` for
  local dev (`command === "build"` check) - Vite applies `base` to both by
  default, which is what put the prefix in local dev URLs before this was
  fixed.
- `dashboard/public/.nojekyll` - an empty marker file GitHub Pages looks for to
  confirm it shouldn't run Jekyll processing on the deployed artifact.
- The Supabase URL/anon key are baked in at build time as plain (non-secret)
  build args in the GitHub Actions workflow - safe, since the anon key is
  meant to ship in a public bundle; RLS is the actual boundary, not key
  secrecy.
- Repo Settings → Pages → Source must be **GitHub Actions**, not "Deploy from
  a branch" - if you ever see the live site showing a generic Jekyll-rendered
  README instead of the dashboard, check that setting first.

## Adding a new view

Add a component under `src/components/`, query Supabase with the existing
client (`import { supabase } from "../lib/supabase"`), add its type to
`types.ts` if it doesn't already mirror an existing table, and render it in
`App.tsx`. If it needs to write data, decide whether it should require
sign-in (most things involving engine behavior should) and add an RLS policy
for the `authenticated` role accordingly - don't forget `anon` too if
unauthenticated users should also see it.
