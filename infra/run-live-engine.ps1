<#
Run the LIVE engine in this console, for a manual/interactive session.

THIS IS NO LONGER HOW THE LIVE ENGINE STARTS ON THE VPS. The scheduled task now
executes python directly:

    C:\ForexAI\.venv\Scripts\python.exe C:\ForexAI\scripts\run_engine.py --env-file C:\ForexAI\.env.live

which is the same shape as the demo task, and it is why restarting the live
engine is now just:

    Stop-ScheduledTask -TaskName "ForexAI-Engine-Live"
    Start-ScheduledTask -TaskName "ForexAI-Engine-Live"

WHY THAT CHANGED. This script used to BE the task: Task Scheduler ran
powershell.exe running this file, and this file exported the live settings and
then launched python as a child. So Task Scheduler owned the wrapper, not the
engine. Stopping the task killed this script and left the python running -
reparented, still polling, still heartbeating, still holding its MT5 connection.
Starting the task again produced TWO live engines on one account, which happened
on 2026-09-05 (heartbeat gaps went from a clean ~61s to 20/41/20/40s). Every
workaround for that - process-tree walks over WMI, pid files, orphan sweeps -
was solving a problem that only existed because of the wrapper.

The settings this script used to export now live in .env.live, which
scripts/run_engine.py loads via --env-file. So this file no longer configures
anything; it is a convenience for running the live engine in a visible console.

SAFETY. Unchanged, and NOT provided by this script. Four independent guards
decide whether a real order can be placed - see docs/going-live.md. As of
2026-09-05 all four are open for london_breakout_v1 on a funded account, so this
command places real trades. The engine itself refuses to start if the live
account is not fully pinned (MT5_TERMINAL_PATH / login / password / server) or
if TEST_MODE is true; those checks live in scripts/run_engine.py and
engine/loop.py, where they apply however the engine was started.
#>

param(
    [string]$RepoDir = "C:\ForexAI",
    [string]$EnvFile = ""
)

$ErrorActionPreference = "Stop"

if (-not $EnvFile) { $EnvFile = Join-Path $RepoDir ".env.live" }
$python = Join-Path $RepoDir ".venv\Scripts\python.exe"
$script = Join-Path $RepoDir "scripts\run_engine.py"

if (-not (Test-Path $EnvFile)) {
    throw "Missing '$EnvFile'. Copy .env.live.example to .env.live and fill it in - it is what makes this process the LIVE engine rather than a second demo one."
}
if (-not (Test-Path $python)) { throw "$python not found - create the venv first." }

Write-Host "Starting LIVE engine in this console"
Write-Host "  env:  $EnvFile"
Write-Host "  log:  $RepoDir\logs\engine-icmarkets-live.log"
Write-Host "  NOTE: the scheduled task does not use this script - see the header."
Write-Host ""

& $python $script --env-file $EnvFile
