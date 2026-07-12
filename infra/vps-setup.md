# VPS + demo account setup (your side)

Claude can't provision a VPS, create broker/hosting accounts, or remote into a
machine it doesn't have access to - these steps are yours. This doc is guidance,
not something executed automatically.

## 1. IC Markets MT5 demo account

Sign up directly on IC Markets' own site. Once created, note the **MT5 server
name** shown in your account details (e.g. something like
`ICMarketsSC-Demo`) - you'll need it for `.env` (`MT5_SERVER`) and it tells you
which data center your trades route through, which matters for step 2.

## 2. Choosing the VPS

What actually matters here, in priority order:

1. **Windows Server** (2019/2022) - the `MetaTrader5` Python package is
   Windows-only.
2. **Low latency to your MT5 server's data center** - check what region/data
   center your demo account's server resolves to; pick a VPS region close to
   it rather than guessing. A few hundred km of difference is usually
   negligible for this system's timeframes (H1 execution), so don't over-index
   on shaving milliseconds - this isn't HFT.
3. **Modest but real specs**: 2+ vCPU, 4GB+ RAM, SSD. MT5 terminal + a Python
   process are both light; this is about headroom for stability, not raw power.
4. **An actual uptime SLA** - avoid bottom-tier VPS with no reliability
   guarantee, given the whole point of self-hosting is control over uptime.

Two reasonable categories of provider:

- **Purpose-built "forex VPS"** (marketed specifically for MT4/5) - pre-tuned
  and often located near common broker data centers, so latency matching is
  mostly done for you. Usually costs more than generic cloud compute.
- **General-purpose cloud Windows VM** (e.g. a standard cloud provider's
  Windows Server offering) - cheaper and more flexible, but you pick the
  region yourself and do a bit more setup.

Either is a reasonable choice; there's no single objectively-correct provider
here since pricing/regions change - pick based on the criteria above once you
know your MT5 server's data center.

## 3. On the VPS, once it's up

1. RDP in, install the MT5 terminal, log in with your demo credentials, leave
   it running and logged in.
2. Install Python 3.11+.
3. Get this repo onto the VPS (once it exists on GitHub - Phase 0 checklist).
4. Copy `.env.example` to `.env`, fill in `MT5_LOGIN` / `MT5_PASSWORD` /
   `MT5_SERVER` / `MT5_TERMINAL_PATH` and the Supabase/Telegram values as they
   become available.
5. (Phase 1) Install NSSM and wrap the engine's entrypoint as a Windows
   service, so it survives reboots and restarts automatically on crash.

None of this is needed to keep working on the codebase locally - Phases 0-2 of
`PLAN.md` are buildable and testable without the VPS existing yet. It becomes
required once Phase 1 needs to prove live MT5 connectivity.
