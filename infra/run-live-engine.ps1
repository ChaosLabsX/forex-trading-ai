<#
Launches the LIVE engine process.

One repo, two engines: this sets environment variables, which OVERRIDE .env
(pydantic-settings precedence is env vars > .env file > defaults). So the demo
engine keeps using .env as-is, and this process differs only where it must -
account, terminal, log file, digest.

SAFETY - four independent guards keep this process from placing a real order.
All four must be deliberately undone; none is a config typo away:

  1. TEST_MODE=false below. DefaultRiskEngine refuses to size ANY order when
     TEST_MODE is off (live sizing is unimplemented), so nothing is ever
     approved. Counter-intuitive but correct: TEST_MODE=TRUE would be the
     dangerous setting here, because it would size real 0.01-lot orders.
  2. engine/gating.py LIVE_SIZING_IMPLEMENTED = False - blocks every strategy
     account-wide on any live account.
  3. accounts.enabled = false for icmarkets-live (migration 0010).
  4. strategy_accounts.enabled = false for every strategy on live.

Running this today is therefore safe and useful: it proves the live plumbing
(terminal attach, heartbeat, dashboard, Telegram) works, while placing nothing.
#>

param(
    # The LIVE terminal must be a SECOND, separate MT5 installation from the demo
    # one. MetaTrader5's bridge attaches to one terminal per process, and
    # mt5.initialize(path=...) is what disambiguates them - without this the
    # engine could attach to the demo terminal and mislabel everything.
    [string]$TerminalPath = "C:\Program Files\MetaTrader 5 IC Markets Live\terminal64.exe",
    [string]$RepoDir = "C:\ForexAI"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $TerminalPath)) {
    throw "Live MT5 terminal not found at '$TerminalPath'. Install a SECOND MT5 terminal for the live account and pass -TerminalPath, or edit the default in this script."
}

$env:MT5_TERMINAL_PATH     = $TerminalPath
$env:ACCOUNT_KEY           = "icmarkets-live"
$env:TEST_MODE             = "false"   # guard 1 - see header
$env:DAILY_SUMMARY_ENABLED = "false"   # the demo engine sends one digest covering both accounts

Write-Host "Starting LIVE engine (account icmarkets-live, execution disabled by design)"
Write-Host "  terminal: $TerminalPath"
Write-Host "  log:      $RepoDir\logs\engine-icmarkets-live.log"

& "$RepoDir\.venv\Scripts\python.exe" "$RepoDir\scripts\run_engine.py"
