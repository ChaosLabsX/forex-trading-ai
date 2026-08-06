# Dashboard

React + TypeScript SPA (Vite), in `dashboard/`. Deployed to GitHub Pages via
`.github/workflows/deploy-dashboard.yml` on every push to `main` touching
`dashboard/**`. See [`dashboard/README.md`](../dashboard/README.md) for local
setup commands.

## Structure

```
src/
  lib/
    supabase.ts          creates the Supabase client from VITE_SUPABASE_URL / VITE_SUPABASE_ANON_KEY
    useAuth.ts            hook: current session, signIn, signOut
    useDashboardData.ts   ONE polling loop (15s); derives per-account health once,
                          so no component re-invents the staleness/paused rule
    useStrategyLab.ts     registries + latest evaluation per (strategy, account)
    format.ts             date/money/relative-time formatting helpers
  components/
    Login.tsx            the full-page gate - the only thing a signed-out visitor sees
    Dashboard.tsx        signed-in layout: topbar, paused banner, stat tiles, sections, account settings
    StatTiles.tsx        KPI row: engines, open trades, total P&L, win rate
    AccountFilter.tsx    scope selector - deliberately NO "All": summing demo play
                         money with real money is a figure you cannot trust
    StrategyLab.tsx      ranked verdicts, readiness counts, per-account toggles
    Readiness.tsx        the "how close to READY" widgets: ReadinessMeter (one %),
                         TradeProgress (trades toward 100), GateList (the five checks)
    StrategyReport.tsx   per-strategy deep view: metrics, equity curve, CI-vs-zero bar
    Engines.tsx          one card per account: status + its own controls
    PausedBanner.tsx     loud full-width alert + one-click resume, shown only while paused
    Controls.tsx         pause/resume/emergency-close-all, TARGETED at one account -
                         an untargeted command silently hits whichever engine defaults to it
    OpenTrades.tsx       trades where status=OPEN
    TradeHistory.tsx     trades where status=CLOSED
    SignalsFeed.tsx      recent signals, joined with ai_reviews (rationale in a disclosure)
    SetPassword.tsx      inside the "Account settings" disclosure at the bottom
  types.ts          TS types mirroring the Supabase schema
App.tsx             the gate: loading spinner -> Login (no session) -> Dashboard (session)
```

No routing library - it's one page. No state management library -
`useDashboardData` runs a single 15s polling loop and passes slices down as
props (nothing here needs sub-second freshness).

Dark theme only (`color-scheme: dark`), tokens in `src/index.css`. Status
colors are the fixed dataviz status palette and are always paired with a text
label (LIVE/OFFLINE, ▲ LONG / ▼ SHORT) - never color alone. Tables use
`tabular-nums` for numeric columns; below 700px each table collapses into
stacked cards via CSS (`thead` hidden, `td::before` renders the column label
from `data-label`), so nothing scrolls horizontally on phones.

## The readiness meter (how the percentage is computed)

The lab table's **Progress to READY** column leads with a single percentage per
strategy, from `readinessScore()` in `lib/useStrategyLab.ts`. The same function
feeds the "Closest to READY" stat tile, so the tile and the row cannot disagree.

Each of the five gates in `readinessGates()` carries an equal 20% share:

| Gate | Credit |
|---|---|
| 100+ closed trades | **partial** - `min(trades / 100, 1) x 20%` |
| Expectancy > 0 | 20%, all-or-nothing |
| 95% CI clears zero | 20%, all-or-nothing |
| Profit factor >= 1.2 | 20%, all-or-nothing |
| Max drawdown <= 15R | 20%, all-or-nothing |

Only the sample gate pays partial credit, because it is the only one that is a
matter of accumulation. A profit factor of 1.1 has **not** half-passed a 1.2 bar,
and paying it out as 10% would read as "nearly there" for a strategy that may
never arrive - the exact misread `verdictEta` already refuses to make by
projecting an ETA to the sample gate only.

Two properties that are deliberate:

- **100% is reserved for every gate met.** Without that floor, 98 trades with all
  four quality gates passed rounds to 100% while the badge beside it still reads
  NOT READY - a number contradicting the verdict next to it. Anything short of
  all five gates is capped at 99%.
- **It can go DOWN.** It is a snapshot of gates cleared right now, not a loading
  bar: more trades can break a gate that was passing, and the evaluator demoting
  a decayed strategy is the system working. The meter's tooltip says so.

The percentage is the coarse answer, `GateList` shows which checks are met, and
the evaluator's own `verdict_reason` underneath is the precise binding
constraint. The evaluator remains the sole authority on the verdict; this is
presentation only.

## Auth model

**Everything requires sign-in.** A signed-out visitor sees only the login
gate - and this is enforced at the database, not just the UI: migration
`0008_require_login_for_monitoring.sql` revoked the anon role's `SELECT` on
all monitoring tables (which migrations 0005/0007 had originally granted, from
the earlier public-monitoring design). The anon key now only powers the auth
endpoints themselves.

- **Reading** signals/trades/heartbeats/ai_reviews: `authenticated` role only
  (grants/policies from migration `0007`).
- **Writing** (pause/resume/emergency-close-all): `Controls.tsx` inserts into
  `commands` with `created_by: session.user.id`; RLS only allows
  `authenticated` to insert, and only with `auth.uid() = created_by`.
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

- `vite.config.ts`: `base` is `/` because the dashboard is served from a GitHub
  Pages **custom domain** (`forex-automation.chaoslabsx.com`), which serves at
  the domain root. If it ever reverts to the bare `chaoslabsx.github.io/<repo>/`
  project-page URL, `base` must become `/<repo>/` or every asset 404s and the
  page renders blank.
- **`dashboard/index.html` is Vite's source entry, not a servable page.** It
  loads `/src/main.tsx`, which no browser can execute, so opening it from a
  plain static server (VS Code Live Server, `file://`) renders white with a 404
  for `/src/main.tsx`. Serving the *built* `dist/` from a subfolder on such a
  server fails too, for a second reason: `base: '/'` sends every asset request
  to the server root. `npm run build:static` builds with `base: './'` and the
  service worker disabled for exactly this case; `npm run dev` remains the way
  to actually develop. Details in [`../dashboard/README.md`](../dashboard/README.md).
- `dashboard/public/CNAME` - one line naming the custom domain. Vite copies it
  verbatim into the build output, which is how GitHub Pages learns the domain on
  each deploy. A custom domain is globally unique to one repo across GitHub, so
  it can't be shared with another project.
- `dashboard/public/.nojekyll` - an empty marker file GitHub Pages looks for to
  confirm it shouldn't run Jekyll processing on the deployed artifact.
- The Supabase URL/anon key are baked in at build time as plain (non-secret)
  build args in the GitHub Actions workflow - safe, since the anon key is
  meant to ship in a public bundle; RLS is the actual boundary, not key
  secrecy.
- Repo Settings → Pages → Source must be **GitHub Actions**, not "Deploy from
  a branch" - if you ever see the live site showing a generic Jekyll-rendered
  README instead of the dashboard, check that setting first.

## PWA

Installable as "Forex AI" via `vite-plugin-pwa` (`generateSW` strategy,
`registerType: 'autoUpdate'`). Manifest/icons are configured directly in
`vite.config.ts`, not a static `manifest.webmanifest` in `public/` - the
plugin generates a base-path-correct one at build time. Icons live in
`dashboard/public/` (`favicon.ico`, `favicon-96x96.png`, `apple-touch-icon.png`,
`pwa-192x192.png`, `pwa-512x512.png`).

**The service worker precaches only the app shell** (JS/CSS/HTML/icons) - no
`runtimeCaching` rule is defined for the Supabase origin, so API calls are
never intercepted or cached by the service worker; they always hit the
network. This is deliberate: caching trading data would mean showing stale
signals/trades/P&L as if current, which is actively misleading for a
financial monitoring tool. If offline, the app shell still loads but shows
no/stale-in-memory data rather than a false "this is current" view.

## Adding a new view

Add a component under `src/components/`, query Supabase with the existing
client (`import { supabase } from "../lib/supabase"`), add its type to
`types.ts` if it doesn't already mirror an existing table, and render it in
`App.tsx`. If it needs to write data, decide whether it should require
sign-in (most things involving engine behavior should) and add an RLS policy
for the `authenticated` role accordingly - don't forget `anon` too if
unauthenticated users should also see it.
