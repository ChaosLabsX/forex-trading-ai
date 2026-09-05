<#
Registers the LIVE engine's Scheduled Task, alongside the existing demo task.

Run this on the VPS in an Administrator PowerShell, AFTER:
  - a SECOND MT5 terminal is installed and logged into the real IC Markets
    account, with Algo Trading enabled (see infra/vps-setup.md)
  - a shortcut to that second terminal is in shell:startup, so it comes back
    after a reboot the same way the demo terminal does

Two engines, two terminals, two accounts, two log files, one repo. They share
nothing but the code - see infra/run-live-engine.ps1 for how the config is
overridden per process.

Registering the task does not by itself enable live trading - four independent
guards do that, and they are described in run-live-engine.ps1's header and
docs/going-live.md.

Do NOT read that as "this cannot trade". As of 2026-09-05 all four guards are
open for london_breakout_v1 on the funded live account, so an engine started by
this task WILL place real orders. An earlier version of this header claimed
execution was blocked "until risk-based position sizing exists"; sizing exists,
and the claim outlived the fact it was based on. Check the guards, never a
comment.
#>

param(
    [string]$TerminalPath = "C:\Program Files\MetaTrader 5 IC Markets Live\terminal64.exe",
    [string]$RepoDir = "C:\ForexAI"
)

$ErrorActionPreference = "Stop"
$TaskName = "ForexAI-Engine-Live"
$Runner = Join-Path $RepoDir "infra\run-live-engine.ps1"
$User = "$env:USERDOMAIN\$env:USERNAME"

if (-not (Test-Path (Join-Path $RepoDir ".venv\Scripts\python.exe"))) {
    throw "Python venv not found - run vps-bootstrap.ps1 first."
}
if (-not (Test-Path $Runner)) {
    throw "$Runner not found - git pull first."
}
if (-not (Test-Path $TerminalPath)) {
    throw "Live MT5 terminal not found at '$TerminalPath'. Install the second terminal first, or pass -TerminalPath."
}

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$Runner`" -TerminalPath `"$TerminalPath`" -RepoDir `"$RepoDir`"" `
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
Write-Host "Live ORDER EXECUTION remains disabled by design - this engine will connect,"
Write-Host "heartbeat and report, but place no trades. See docs/safety-rails.md."
Write-Host ""
Write-Host "Start it now:   Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "Watch it:       Get-Content $RepoDir\logs\engine-icmarkets-live.log -Tail 20 -Wait"
