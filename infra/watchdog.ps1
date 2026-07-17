<#
ForexAI watchdog - a dead-man's switch for the engines.

The engine cannot announce its own death: a crashed process, a logged-out MT5
terminal, or a hung loop all produce the same thing the lab produces when it
simply has nothing to say - silence. Until this existed, "no READY alert" and
"the engine died three days ago" were indistinguishable from a phone.

So this runs OUTSIDE the engine entirely: a scheduled task (every 5 minutes,
as SYSTEM - no interactive session needed, so it also survives logoff) that
reads the latest engine_heartbeats row per enabled account straight from
Supabase and sends a Telegram alert when one goes stale. It shares nothing
with the engine but the .env file: no Python, no venv, no MT5. If the engine
process, the venv, or the Python install itself is broken, this still runs.

Deliberately duplicates Telegram delivery (engine copy lives in
engine/reporting.py): routing the alert through the engine's own notifier
would make the watchdog depend on the very thing it watches.

Alert policy: one alert when an account goes silent, a reminder every
$RealertMinutes while it stays silent, one all-clear when it returns. A
watchdog that cannot reach Supabase alerts about THAT ("blind" is not "all
clear") under the same rate limit.

Register once (elevated PowerShell on the VPS):

  $action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File C:\ForexAI\infra\watchdog.ps1"
  $trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Minutes 5) -RepetitionDuration (New-TimeSpan -Days 3650)
  $principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount
  $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew
  Register-ScheduledTask -TaskName "ForexAI-Watchdog" -Action $action -Trigger $trigger `
    -Principal $principal -Settings $settings
#>
param(
    [switch]$DryRun,                                          # log what would be sent, send nothing
    [string]$EnvFile = "C:\ForexAI\.env",
    [string]$StateFile = "C:\ForexAI\logs\watchdog-state.json",
    [string]$LogFile = "C:\ForexAI\logs\watchdog.log",
    [int]$StaleMinutes = 5,                                   # engine beats every 60s; 5 missed beats = silent
    [int]$RealertMinutes = 60
)

$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

# Built from code points, NOT literals. PowerShell 5.1 reads a .ps1 without a
# UTF-8 BOM as the system codepage, which turns "*" into mojibake at PARSE time
# - "\U0001F6A8" arrived in Telegram as "ðŸš¨". Constructing
# them at runtime is immune to how this file is saved, committed, or checked out.
# The icon is the signal here (alarm vs all-clear at a glance), so it has to survive.
$E_ALARM = [char]::ConvertFromUtf32(0x1F6A8)  # rotating light
$E_OK    = [char]::ConvertFromUtf32(0x2705)   # white heavy check mark
$SEP     = [string][char]0x00B7               # middle dot

function Write-Log([string]$text) {
    $line = "{0:u} {1}" -f (Get-Date).ToUniversalTime(), $text
    try { Add-Content -Path $LogFile -Value $line } catch {}
    if ($DryRun) { Write-Host $line }
}

# --- config from the engine's own .env (no second copy of any secret) --------
$cfg = @{}
foreach ($line in Get-Content $EnvFile) {
    if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$') { $cfg[$matches[1]] = $matches[2].Trim() }
}
foreach ($k in 'SUPABASE_URL', 'SUPABASE_SERVICE_ROLE_KEY', 'TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID') {
    if (-not $cfg[$k]) { Write-Log "FATAL missing $k in $EnvFile"; throw "missing $k in $EnvFile" }
}
$headers = @{ apikey = $cfg['SUPABASE_SERVICE_ROLE_KEY']; Authorization = "Bearer $($cfg['SUPABASE_SERVICE_ROLE_KEY'])" }
$base = $cfg['SUPABASE_URL'].TrimEnd('/')

function Send-Alert([string]$text) {
    if ($DryRun) { Write-Log ("DRYRUN would send: " + ($text -replace "`n", " / ")); return }
    # Telegram speaks UTF-8. Invoke-RestMethod with a hashtable body encodes
    # using the system codepage in PS 5.1, which mangles anything non-ASCII, so
    # send JSON encoded to UTF-8 bytes explicitly rather than letting PowerShell
    # choose. Belt-and-braces with the code-point constants above: one protects
    # the characters at parse time, this protects them on the wire.
    $payload = @{ chat_id = $cfg['TELEGRAM_CHAT_ID']; text = $text } | ConvertTo-Json -Compress
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($payload)
    Invoke-RestMethod -Method Post `
        -Uri "https://api.telegram.org/bot$($cfg['TELEGRAM_BOT_TOKEN'])/sendMessage" `
        -Body $bytes -ContentType 'application/json; charset=utf-8' | Out-Null
}

# --- state: what we've already alerted about, so silence isn't spammed -------
$state = @{}
if (Test-Path $StateFile) {
    try {
        # Assign FIRST, then enumerate. @(<pipeline>) around ConvertFrom-Json
        # wraps the parsed array inside a second array (PS 5.1 emits it as one
        # pipeline object), so foreach would see a single Object[] "entry"
        # whose .key member-enumerates - which silently corrupted this file.
        # The .key guard drops any such junk from a previously corrupted file.
        $parsed = Get-Content $StateFile -Raw | ConvertFrom-Json
        foreach ($entry in @($parsed)) {
            if ($entry -and $entry.PSObject.Properties['key'] -and $entry.key -is [string] -and $entry.key) {
                $state[$entry.key] = $entry
            }
        }
    } catch { $state = @{} }
}
function Get-Entry([string]$key) {
    if (-not $state.ContainsKey($key)) {
        $state[$key] = [pscustomobject]@{ key = $key; down = $false; lastAlertUtc = "" }
    }
    return $state[$key]
}
function Should-Alert($entry) {
    if (-not $entry.down) { return $true }
    if (-not $entry.lastAlertUtc) { return $true }
    return ([DateTimeOffset]::UtcNow - [DateTimeOffset]::Parse($entry.lastAlertUtc)).TotalMinutes -ge $RealertMinutes
}
function Save-State {
    # ConvertTo-Json unwraps single-element pipelines; force an array so a
    # one-account state file round-trips.
    ConvertTo-Json @($state.Values) -Depth 3 | Set-Content -Path $StateFile -Encoding utf8
}

# --- can we see Supabase at all? Blind is an alert, not an all-clear ---------
$blind = Get-Entry "__supabase__"
try {
    $accounts = @(Invoke-RestMethod -Uri "$base/rest/v1/accounts?enabled=eq.true&select=key" -Headers $headers)
} catch {
    if (Should-Alert $blind) {
        Send-Alert "$E_ALARM WATCHDOG BLIND`ncannot reach Supabase - engine state unknown`n$($_.Exception.Message)"
        $blind.down = $true
        $blind.lastAlertUtc = [DateTimeOffset]::UtcNow.ToString("o")
    }
    Write-Log "ERROR cannot reach Supabase: $($_.Exception.Message)"
    Save-State
    exit 1
}
if ($blind.down) {
    Send-Alert "$E_OK WATCHDOG OK`nSupabase reachable again"
    $blind.down = $false
    $blind.lastAlertUtc = ""
}

# --- the actual check: one latest heartbeat per enabled account --------------
foreach ($account in $accounts) {
    $key = $account.key
    $entry = Get-Entry $key
    $beats = @(Invoke-RestMethod `
        -Uri "$base/rest/v1/engine_heartbeats?account_key=eq.$key&select=created_at,status&order=created_at.desc&limit=1" `
        -Headers $headers)

    if ($beats.Count -eq 0) {
        $stale = $true
        $ageText = "never (no heartbeat ever recorded)"
    } else {
        $age = [DateTimeOffset]::UtcNow - [DateTimeOffset]::Parse($beats[0].created_at)
        $stale = $age.TotalMinutes -gt $StaleMinutes
        $ageText = "{0}m" -f [math]::Round($age.TotalMinutes)
    }

    if ($stale) {
        if (Should-Alert $entry) {
            Send-Alert "$E_ALARM ENGINE SILENT  $SEP  $($key.ToUpper())`nno heartbeat for $ageText (threshold ${StaleMinutes}m)`ncheck the VPS: task state, Get-Process python, MT5 login"
            $entry.down = $true
            $entry.lastAlertUtc = [DateTimeOffset]::UtcNow.ToString("o")
        }
        Write-Log "SILENT $key age=$ageText"
    } else {
        if ($entry.down) {
            Send-Alert "$E_OK ENGINE BACK  $SEP  $($key.ToUpper())`nheartbeat resumed ($ageText ago)"
        }
        $entry.down = $false
        $entry.lastAlertUtc = ""
        Write-Log "OK $key age=$ageText status=$($beats[0].status)"
    }
}

Save-State
