<#
Run this on the VPS (via RDP), in an Administrator PowerShell window, AFTER:
  - vps-bootstrap.ps1 has been run
  - the MT5 terminal is installed, logged into ICMarketsSC-Demo, and Algo
    Trading is enabled
  - C:\ForexAI\.env exists with real secrets
  - Windows auto-login is configured for this account (see vps-setup.md)

Registers a Scheduled Task that starts the engine at logon and restarts it
on failure. NOT an NSSM/Windows service - MT5's Python bridge needs an
interactive desktop session, which a Session-0 service can't provide. A
Scheduled Task with an "at logon" trigger runs in the same session the
auto-login desktop uses, which is what MT5 needs. See docs/safety-rails.md.
#>

$ErrorActionPreference = "Stop"
$RepoDir = "C:\ForexAI"
$PythonExe = Join-Path $RepoDir ".venv\Scripts\python.exe"
$ScriptPath = Join-Path $RepoDir "scripts\run_engine.py"
$TaskName = "ForexAI-Engine"
$User = "$env:USERDOMAIN\$env:USERNAME"

if (-not (Test-Path $PythonExe)) {
    throw "Python venv not found at $PythonExe - run vps-bootstrap.ps1 first."
}
if (-not (Test-Path (Join-Path $RepoDir ".env"))) {
    throw "$RepoDir\.env not found - create it before registering the task (see vps-setup.md)."
}

$action = New-ScheduledTaskAction -Execute $PythonExe -Argument $ScriptPath -WorkingDirectory $RepoDir
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

Write-Host "Registered scheduled task '$TaskName':"
Write-Host "  - Starts automatically when $User logs on (including after a reboot, via auto-login)"
Write-Host "  - Restarts automatically on failure (up to 999 times, 1 min apart)"
Write-Host ""
Write-Host "IMPORTANT: also confirm the MT5 terminal itself is set to launch at logon"
Write-Host "(a shortcut in shell:startup, or its own 'start automatically' option) -"
Write-Host "this task only manages the Python engine, not the terminal."
Write-Host ""
Write-Host "To start it right now without logging off/on:"
Write-Host "  Start-ScheduledTask -TaskName '$TaskName'"
Write-Host ""
Write-Host "To check on it:"
Write-Host "  Get-ScheduledTaskInfo -TaskName '$TaskName'"
Write-Host "  Get-Content $RepoDir\logs\engine-icmarkets-demo.log -Tail 20 -Wait"
