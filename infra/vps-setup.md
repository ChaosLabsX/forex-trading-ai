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

Six steps to a running, self-watching lab - 2 scripts (one committed, one given
directly in chat since it carries real secrets), 3 things that must stay manual
(no remote-access tool reaches the VPS, and account/Windows passwords are
deliberately kept out of anything scripted or seen by Claude), and the watchdog
registration. Steps 7-8 are optional/cleanup.

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

### 5. Register the watchdog (do not skip - it is the dead-man's switch)

The engine cannot report its own death: a crash, a logged-out terminal, or a
hung loop all produce the same silence the lab produces when it simply has
nothing to say. `infra/watchdog.ps1` runs **outside** the engine and alerts on
Telegram when an enabled account's heartbeat goes stale. Rebuilding the VPS
without this leaves you unable to tell "no verdict yet" from "dead for three
days". See [`docs/safety-rails.md`](../docs/safety-rails.md).

Elevated PowerShell, one paste:

```powershell
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
  -Argument "-NoProfile -ExecutionPolicy Bypass -File C:\ForexAI\infra\watchdog.ps1"
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
  -RepetitionInterval (New-TimeSpan -Minutes 5) -RepetitionDuration (New-TimeSpan -Days 3650)
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName "ForexAI-Watchdog" -Action $action -Trigger $trigger `
  -Principal $principal -Settings $settings -Force

Start-ScheduledTask -TaskName "ForexAI-Watchdog"
Start-Sleep -Seconds 10
Get-Content C:\ForexAI\logs\watchdog.log -Tail 3
```

Expect `OK icmarkets-demo age=0m status=running` and **no** Telegram message -
the watchdog only speaks when something is wrong or has recovered. It reads
`C:\ForexAI\.env` for Supabase + Telegram, so step 4 must be done first. Runs
as SYSTEM, so it survives logoff; `-DryRun` logs what it *would* send without
sending.

To prove it actually fires, stop the engine for ~10 minutes and confirm a 🚨
arrives - the only test that distinguishes a working watchdog from a silent one.

### 6. Verify end-to-end

- Confirm `logs\engine-icmarkets-demo.log` showed a clean connect + first heartbeat (the
  previous script's tail should already show this). Read the **startup** lines,
  not just recent activity: look for `attached: account <n> (<server>)` with no
  `reconnect failed` after it. A limping engine and a healthy one are
  indistinguishable further down the log (see `safety-rails.md`).
- Check the dashboard - the Engine tile should flip to LIVE within ~60s.
- Reboot the VPS (`Restart-Computer`) once, wait a few minutes, and confirm
  the terminal + engine both come back on their own (proves auto-login +
  Task Scheduler are wired correctly) - this is the actual test of "survives
  a reboot," not just reading the config.

### Telling the two console windows apart

Both engines are now started identically - Task Scheduler executing
`.venv\Scripts\python.exe scripts\run_engine.py` - which is exactly what makes
restarting them one identical command each. The cost is that their consoles
became indistinguishable, and `MainWindowTitle` is empty under Windows
Terminal's ConPTY, so there is nothing to match on from outside.

So each engine names its own window at startup:

| Window title | Which engine |
|---|---|
| `ForexAI  -  DEMO LAB  (icmarkets-demo)` | the lab |
| `*** ForexAI  -  LIVE / REAL MONEY ARMED  (icmarkets-live) ***` | real money, guard 1 on |
| `ForexAI  -  LIVE account, trading OFF  (icmarkets-live)` | live account, guard 1 off |

The live title is loud on purpose. **Closing a console kills the process
attached to it**, so mistaking the real-money window for the lab is a mistake
worth making hard to make.

You do not have to use the consoles at all, though - each engine has its own log:

```powershell
Get-Content C:\ForexAI\logs\engine-icmarkets-live.log -Tail 20 -Wait
```

### Restarting the LIVE engine

Same as the demo lab, because the live task now executes python directly too:

```powershell
Stop-ScheduledTask -TaskName "ForexAI-Engine-Live"; Start-ScheduledTask -TaskName "ForexAI-Engine-Live"
```

That is a recent change and the reason is worth knowing, because the old
behaviour was a real hazard.

The task used to execute `powershell.exe` running `infra/run-live-engine.ps1`,
which exported the live settings and then launched python as a **child**. Task
Scheduler owned the wrapper, not the engine. So `Stop-ScheduledTask` killed the
wrapper and left the engine running - reparented, still polling, still
heartbeating, still holding its MT5 connection - and starting the task again put
**two live engines on one account**. That happened on 2026-09-05: `icmarkets-live`
heartbeat gaps went from a clean ~61s to 20/41/20/40s, the signature of two
engines on 61s cycles offset from each other. Nothing had traded yet, so it was
luck rather than design that nothing was double-placed.

Everything built to work around that - process-tree walks over WMI, orphan
sweeps, pid files - was solving a problem that only existed because of the
wrapper. The settings it exported now live in `.env.live`, which
`scripts/run_engine.py` loads via `--env-file`, so Task Scheduler can own the
engine itself:

```
Execute : C:\ForexAI\.venv\Scripts\python.exe
Argument: "C:\ForexAI\scripts\run_engine.py" --env-file "C:\ForexAI\.env.live"
```

**Do not "kill every python running run_engine.py".** The demo lab runs the
identical command line, and stopping the wrong one silently halts the lab that
is accumulating the 100 trades a readiness verdict needs. Stop the *task*.

**`infra/restart-live-engine.ps1` still exists** and is worth using when you want
the restart verified rather than assumed. It stops the task, waits for the engine
to actually exit, starts it again, and waits for a **new** pid to appear in
`logs\engine-icmarkets-live.pid` - which `run_engine.py` writes at startup - then
confirms the `attached:` line for this restart specifically. Plain Stop/Start is
enough; this tells you it worked.

**Guards that moved.** `run-live-engine.ps1` used to refuse to start if the live
credentials were blank. Those checks now live in `scripts/run_engine.py`
(`_require_pinned`: account key, terminal path must be a real file, login,
password, server) and `engine/loop.py` (refuses `TEST_MODE=true` on a live
account, which would size real orders at the broker minimum and ignore
`risk_pct`). They had to move: a guard that lives only in a launcher you have
stopped using is not a guard.

### 7. (Optional) Add the LIVE account's second engine

**This section is written for the setup stage, when the live account held $0 and
every guard was shut.** That is no longer the state: since 2026-09-05 the account
is funded with $200 and `london_breakout_v1` trades it for real. Whether an
engine places orders depends on the four guards in
[`docs/going-live.md`](../docs/going-live.md) - never on a sentence in a runbook.
(An earlier version of this paragraph said execution was blocked "until
risk-based position sizing exists". Sizing shipped; the sentence stayed. That is
the failure mode to watch for in here.)

The steps below are still the right way to stand the second engine up.

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

### 8. Stop the local engine

Once the VPS engine is confirmed running, **do not also run it locally at the
same time** - two independent instances evaluating the same strategy against
the same account could both act on the same signal, effectively doubling a
position unintentionally. Keep only one running at a time; the local setup
remains useful for future development/testing, just not concurrently with the
VPS.
