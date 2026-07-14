<#
Launches the LIVE engine process.

One repo, two engines: this sets environment variables, which OVERRIDE .env
(pydantic-settings precedence is env vars > .env file > defaults). So the demo
engine keeps using .env as-is, and this process differs only where it must -
account, terminal, log file, digest.

SAFETY - four independent guards keep this process from placing a real order.
All four must be deliberately undone; none is a config typo away:

  1. LIVE_TRADING_ENABLED is off (Settings default). engine/gating.py blocks
     every strategy account-wide on a live account while it is off. This is THE
     master switch, and it is deliberately not derived from any feature being
     unimplemented - see docs/going-live.md.
  2. accounts.enabled = false for icmarkets-live (migration 0010).
  3. strategy_accounts.enabled = false for every strategy on live.
  4. Live requires readiness = 'ready', which no strategy has yet.

NOTE: TEST_MODE=false below is NOT a guard - it selects real risk-based sizing
over the demo's fixed micro lot, which is the correct setting for a live
account. (TEST_MODE=true here would be the dangerous one: it would size real
0.01-lot orders.) Safety comes from guard 1, not from this.

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
$env:TEST_MODE             = "false"   # real sizing, not the demo micro lot - NOT a guard
$env:DAILY_SUMMARY_ENABLED = "false"   # the demo engine sends one digest covering both accounts
# LIVE_TRADING_ENABLED is intentionally NOT set here: it defaults to false, and
# turning it on is a deliberate act documented in docs/going-live.md.

Write-Host "Starting LIVE engine (account icmarkets-live, execution disabled by design)"
Write-Host "  terminal: $TerminalPath"
Write-Host "  log:      $RepoDir\logs\engine-icmarkets-live.log"

& "$RepoDir\.venv\Scripts\python.exe" "$RepoDir\scripts\run_engine.py"
