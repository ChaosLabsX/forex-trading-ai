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

### 1. Run the bootstrap script

RDP in, open PowerShell **as Administrator**, then:

```powershell
irm https://raw.githubusercontent.com/ChaosLabsX/forex-trading-ai/main/infra/vps-bootstrap.ps1 | iex
```

(Or copy `infra/vps-bootstrap.ps1`'s contents into a `.ps1` file on the VPS
and run it - either works. It installs Python + Git, clones the repo to
`C:\ForexAI`, and sets up the venv. No secrets touched.)

### 2. Install and log into the MT5 terminal

1. Download the IC Markets MT5 terminal installer from IC Markets' own site
   (inside the VPS's browser).
2. Install it, launch it, log into the `ICMarketsSC-Demo` account with your
   own demo credentials (never put these in `.env` - see step 4).
3. In the toolbar, enable **Algo Trading** (same requirement as local dev -
   `order_send()` fails with retcode 10027 until this is on).
4. Note the terminal's install path (e.g.
   `C:\Program Files\IC Markets - MetaTrader 5\terminal64.exe`) - needed for
   step 5.

### 3. Create `.env`

Create `C:\ForexAI\.env` with the same shape as your local one - real values
via secure copy-paste (RDP clipboard works fine for this), not retyped by
hand. `MT5_LOGIN`/`MT5_PASSWORD` stay blank, same reasoning as local: the
terminal's already logged in, so the Python bridge attaches directly and the
demo password never needs to live in a file.

### 4. Configure Windows auto-login

Run `netplwiz` (Start → Run), uncheck "Users must enter a user name and
password to use this computer," enter this account's credentials when
prompted. This is a GUI step specifically so the password only ever goes
through Windows' own dialog, never a script or anything Claude sees.

**Trade-off worth knowing:** Windows stores this password in the registry in
reversible form (a long-standing Windows limitation, not specific to this
setup). Anyone with admin/physical access to the VPS could retrieve it. This
is why RDP + Windows Firewall hardening (step 6) matters - auto-login raises
the value of keeping unauthorized access out in the first place.

### 5. Auto-start the MT5 terminal at logon

Press `Win+R`, run `shell:startup`, and drop a shortcut to `terminal64.exe`
(from step 2.4) into that folder. It'll now launch automatically whenever
this account logs in - including the automatic logon from step 4.

### 6. Harden the VPS

Run in an Administrator PowerShell:

```powershell
# Confirm Windows Firewall is on for all profiles
Set-NetFirewallProfile -Profile Domain,Public,Private -Enabled True

# Restrict RDP to just what's needed (it's already the only inbound rule
# InterServer opens by default) - verify no unexpected extra rules exist:
Get-NetFirewallRule -Direction Inbound -Enabled True | Where-Object { $_.Action -eq "Allow" } | Format-Table DisplayName, Profile
```

Also worth doing manually:
- Set a strong Windows account password (you'll need it for RDP regardless of
  auto-login, and it's what auto-login's stored credential actually is).
- Windows Update: leave automatic updates on (security patches matter more
  than avoiding a reboot), and rely on auto-login + Task Scheduler (step 7) to
  bring everything back up automatically after any update-triggered restart -
  don't disable updates to dodge this, fix the recovery path instead, which
  is what steps 4/5/7 do.
- Consider changing the RDP port from the 3389 default (reduces automated
  scanning noise; doesn't replace a strong password) - only if you're
  comfortable updating your own RDP client's connection string afterward.

### 7. Register the engine's auto-start task

Only after steps 1-3 are done (venv exists, MT5 is logged in, `.env` exists):

```powershell
cd C:\ForexAI
.\infra\setup-scheduled-tasks.ps1
```

This registers a Scheduled Task that starts the engine when this account logs
on and restarts it automatically on failure. Start it immediately without
waiting for a reboot:

```powershell
Start-ScheduledTask -TaskName "ForexAI-Engine"
Get-Content C:\ForexAI\logs\engine.log -Tail 20 -Wait
```

### 8. Verify end-to-end

- Watch `logs\engine.log` for a clean connect + first heartbeat.
- Check the dashboard - the Engine tile should flip to LIVE within ~60s.
- Reboot the VPS (`Restart-Computer`) once, wait a few minutes, and confirm
  the terminal + engine both come back on their own (proves auto-login +
  Task Scheduler are wired correctly) - this is the actual test of "survives
  a reboot," not just reading the config.

### 9. Stop the local engine

Once the VPS engine is confirmed running, **do not also run it locally at the
same time** - two independent instances evaluating the same strategy against
the same account could both act on the same signal, effectively doubling a
position unintentionally. Keep only one running at a time; the local setup
remains useful for future development/testing, just not concurrently with the
VPS.
