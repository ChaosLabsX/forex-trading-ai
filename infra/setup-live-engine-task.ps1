<#
Registers the LIVE engine's Scheduled Task, alongside the existing demo task.

Run this on the VPS in an Administrator PowerShell, AFTER:
  - a SECOND MT5 terminal is installed and logged into the real IC Markets
    account, with Algo Trading enabled (see infra/vps-setup.md)
  - a shortcut to that second terminal is in shell:startup, so it comes back
    after a reboot the same way the demo terminal does

Two engines, two terminals, two accounts, two log files, one repo. They share
nothing but the code - see .env.live.example for how the config differs.

The task executes python DIRECTLY, exactly as the demo task does, so Task
Scheduler owns the engine itself and stopping the task stops the engine:

    Stop-ScheduledTask -TaskName "ForexAI-Engine-Live"
    Start-ScheduledTask -TaskName "ForexAI-Engine-Live"

Do NOT reintroduce a launcher script between Task Scheduler and python. Task
Scheduler owns what it executes; a wrapper means stopping the task kills the
wrapper and leaves the engine running, reparented and still holding its MT5
connection - and the next start gives you two live engines on one account.

Registering the task does not by itself enable live trading - four independent
guards do that, and they are documented in docs/going-live.md.

Do NOT read that as "this cannot trade". All four guards are currently open for
london_breakout_v1 on the funded live account, so an engine started by this task
WILL place real orders. Check the guards, never a comment.
#>

param(
    [string]$TerminalPath = "C:\Program Files\MetaTrader 5 IC Markets Live\terminal64.exe",
    [string]$RepoDir = "C:\ForexAI"
)

$ErrorActionPreference = "Stop"
$TaskName = "ForexAI-Engine-Live"
$PythonExe = Join-Path $RepoDir ".venv\Scripts\python.exe"
$ScriptPath = Join-Path $RepoDir "scripts\run_engine.py"
$LiveEnv = Join-Path $RepoDir ".env.live"
$User = "$env:USERDOMAIN\$env:USERNAME"

if (-not (Test-Path (Join-Path $RepoDir ".venv\Scripts\python.exe"))) {
    throw "Python venv not found - run vps-bootstrap.ps1 first."
}
if (-not (Test-Path $TerminalPath)) {
    throw "Live MT5 terminal not found at '$TerminalPath'. Install the second terminal first, or pass -TerminalPath."
}
if (-not (Test-Path $LiveEnv)) {
    throw "Missing '$LiveEnv'. Copy .env.live.example to .env.live and fill it in - it is what makes this process the LIVE engine. Without it the task would start a second DEMO engine."
}
# The engine refuses to start unpinned, but failing here is far better than
# failing in a Task Scheduler process with no console attached.
foreach ($required in @("ACCOUNT_KEY", "MT5_LOGIN", "MT5_PASSWORD", "MT5_SERVER", "MT5_TERMINAL_PATH")) {
    $hit = Select-String -Path $LiveEnv -Pattern "^\s*$required\s*=\s*\S" -Quiet
    if (-not $hit) { throw "$required is missing or empty in '$LiveEnv' - see .env.live.example." }
}
if (Select-String -Path $LiveEnv -Pattern "^\s*TEST_MODE\s*=\s*true" -Quiet) {
    throw "TEST_MODE=true in '$LiveEnv'. On a live account that sizes real orders at the broker minimum and ignores risk_pct. Set TEST_MODE=false."
}

# python directly - NOT a powershell wrapper. See the header for why.
$action = New-ScheduledTaskAction `
    -Execute $PythonExe `
    -Argument "`"$ScriptPath`" --env-file `"$LiveEnv`"" `
    -WorkingDirectory $RepoDir

$trigger = New-ScheduledTaskTrigger -AtLogOn -User $User
$settings = New-ScheduledTaskSettingsSet `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -DontStopOnIdleEnd `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -User $User -RunLevel Highest -Force | Out-Null

Write-Host "Registered '$TaskName' (starts at logon, restarts on failure)."
Write-Host ""
Write-Host "Whether it places real orders depends on the four guards in docs/going-live.md,"
Write-Host "starting with LIVE_TRADING_ENABLED in .env.live. Registering the task decides"
Write-Host "nothing about that - and as of 2026-09-05 those guards are OPEN for"
Write-Host "london_breakout_v1 on a funded account, so do not assume this cannot trade."
Write-Host ""
Write-Host "Start it now:   Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "Watch it:       Get-Content $RepoDir\logs\engine-icmarkets-live.log -Tail 20 -Wait"
