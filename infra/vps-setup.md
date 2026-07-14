# VPS setup — Phase 6

Claude can't RDP into the VPS, create accounts, or handle your VPS/Windows
login credentials - every step below needs you at the RDP session. Scripts in
`infra/` automate what safely can be; the rest is an ordered checklist.

## The VPS (already provisioned)

InterServer Windows Cloud Compute, 4 slices (2 cores / 8GB RAM / 160GB SSD),
$20/month, Hyper-V platform.

- Hostname: `vps3493451.trouble-free.net`
- IP: `162.220.166.12`
- Connect via Windows' built-in Remote Desktop Connection (`mstsc`) to that
  IP, using the credentials from InterServer's control panel.

## Why Task Scheduler, not a Windows service

MT5's Python bridge (`mt5.initialize()`) talks to the terminal over local IPC
and needs to run in the **same interactive desktop session** as the terminal
GUI. Windows services (NSSM included) run in Session 0, which is isolated
from any desktop session - a Session-0-wrapped engine can never see MT5,
regardless of how correctly everything else is configured. The fix used here:
**Windows auto-login + Task Scheduler "at logon" triggers** for both the MT5
terminal and the engine, in the same real desktop session. Task Scheduler's
own restart-on-failure settings replace what NSSM would have provided.

## Checklist

Consolidated to 5 steps - 2 scripts (one committed, one given directly in
chat since it carries real secrets) plus 3 things that must stay manual
(no remote-access tool reaches the VPS, and account/Windows passwords are
deliberately kept out of anything scripted or seen by Claude).

### 1. Run the bootstrap script

RDP in, open PowerShell **as Administrator**, then:

```powershell
irm https://raw.githubusercontent.com/ChaosLabsX/forex-trading-ai/main/infra/vps-bootstrap.ps1 | iex
```

Installs Python + Git, clones the repo to `C:\ForexAI`, sets up the venv, and
turns on/confirms Windows Firewall. No secrets touched.

### 2. Install and log into the MT5 terminal (manual - GUI installer, your credentials)

1. Download the IC Markets MT5 terminal installer from IC Markets' own site
   (inside the VPS's browser).
2. Install it, launch it, log into the `ICMarketsSC-Demo` account with your
   own demo credentials (never put these in `.env`).
3. In the toolbar, enable **Algo Trading** (same requirement as local dev -
   `order_send()` fails with retcode 10027 until this is on).

No need to note the install path - the next script finds `terminal64.exe`
itself.

### 3. Configure Windows auto-login (manual - GUI dialog, your Windows password)

Run `netplwiz` (Start → Run), uncheck "Users must enter a user name and
password to use this computer," enter this account's credentials when
prompted. This is a GUI step specifically so the password only ever goes
through Windows' own dialog, never a script or anything Claude sees.

**Trade-off worth knowing:** Windows stores this password in the registry in
reversible form (a long-standing Windows limitation, not specific to this
setup). Anyone with admin/physical access to the VPS could retrieve it. This
is why the firewall hardening in step 1 matters - auto-login raises the value
of keeping unauthorized access out in the first place. Also worth doing
manually: set a strong Windows account password, and consider moving RDP off
port 3389 if you're comfortable updating your own client's connection string.

### 4. Finish setup (second script, given directly in chat - not in this repo)

Ask Claude for it once steps 1-3 are done. It writes `.env` with your real
secrets (never committed, since this repo is public), auto-detects
`terminal64.exe` and drops a shortcut in the Startup folder, registers the
Scheduled Task from `infra/setup-scheduled-tasks.ps1`, starts the engine
immediately, and tails the first bit of log output so you can see it connect
live - all one paste.

### 5. Verify end-to-end

- Confirm `logs\engine-icmarkets-demo.log` showed a clean connect + first heartbeat (the
  previous script's tail should already show this).
- Check the dashboard - the Engine tile should flip to LIVE within ~60s.
- Reboot the VPS (`Restart-Computer`) once, wait a few minutes, and confirm
  the terminal + engine both come back on their own (proves auto-login +
  Task Scheduler are wired correctly) - this is the actual test of "survives
  a reboot," not just reading the config.

### 6. (Optional) Add the LIVE account's second engine

Only when you want the live half running. It is safe to do now: the live engine
connects, heartbeats and reports, and **places no orders** - four independent
guards block execution until risk-based position sizing exists (see
`infra/run-live-engine.ps1`'s header and `docs/safety-rails.md`). Running it
early is how you prove the plumbing works before any money is at stake.

The model is: **two terminals, two engines, two accounts, two log files, one
repo.** MT5's Python bridge attaches to one terminal per process, so the live
account needs its own terminal installation - it cannot share the demo one.

1. Install a **second** MT5 terminal to its own directory (the IC Markets
   installer lets you choose the path, e.g.
   `C:\Program Files\MetaTrader 5 IC Markets Live`). Log it into your **real**
   account and enable Algo Trading.
2. Put a shortcut to that second `terminal64.exe` in `shell:startup` too, so it
   returns after a reboot like the demo terminal does.
3. Register the second task (adjust `-TerminalPath` if you installed elsewhere):

```powershell
cd C:\ForexAI
.\infra\setup-live-engine-task.ps1 -TerminalPath "C:\Program Files\MetaTrader 5 IC Markets Live\terminal64.exe"
Start-ScheduledTask -TaskName "ForexAI-Engine-Live"
Get-Content C:\ForexAI\logs\engine-icmarkets-live.log -Tail 20
```

No `.env` edit is needed: `infra/run-live-engine.ps1` sets `ACCOUNT_KEY`,
`TEST_MODE=false`, `MT5_TERMINAL_PATH` and `DAILY_SUMMARY_ENABLED=false` as
environment variables, which override `.env` for that process only. Both engines
therefore run from one checkout with no config duplication.

Expect the log to say the account is blocked - that is the design working, not a
fault. The dashboard's Accounts section will show the live engine alongside the
demo one.

### 7. Stop the local engine

Once the VPS engine is confirmed running, **do not also run it locally at the
same time** - two independent instances evaluating the same strategy against
the same account could both act on the same signal, effectively doubling a
position unintentionally. Keep only one running at a time; the local setup
remains useful for future development/testing, just not concurrently with the
VPS.
