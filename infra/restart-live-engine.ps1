<#
Restart the LIVE engine, and prove it came back.

A PLAIN RESTART IS ENOUGH. The live task executes python directly, so Task
Scheduler owns the engine itself:

    Stop-ScheduledTask -TaskName "ForexAI-Engine-Live"
    Start-ScheduledTask -TaskName "ForexAI-Engine-Live"

Use this script when you want the restart VERIFIED rather than assumed: it waits
for the old engine to actually exit, for a NEW pid to appear, and for this
restart's own 'attached:' line, then prints what is running.

HOW IT KNOWS WHICH PROCESS IS THE LIVE ENGINE. It reads
logs\engine-icmarkets-live.pid, which scripts/run_engine.py writes at startup and
removes on a clean exit. This matters because the demo lab runs the identical
command line - `.venv\Scripts\python.exe scripts\run_engine.py` - so nothing
about a process's name or arguments can separate them, and stopping the wrong one
silently halts the lab that is accumulating the trades a readiness verdict needs.
Each account writes its own pid file, so there is no ambiguity.

Everything here is Get-Process and file reads. Do NOT reintroduce
`Get-CimInstance Win32_Process`: on this VPS it does not return in usable time,
and a restart script that hangs before it acts restarts nothing.

Usage (elevated PowerShell on the VPS):
    powershell -NoProfile -ExecutionPolicy Bypass -File C:\ForexAI\infra\restart-live-engine.ps1
    ... -EnginePid <id>     when the pid file is missing (see the refusal message)
#>

param(
    [string]$TaskName = "ForexAI-Engine-Live",
    [string]$RepoDir  = "C:\ForexAI",
    [string]$AccountKey = "icmarkets-live",
    [int]$EnginePid = 0,
    # Deadlines, not durations: each wait returns as soon as its condition holds.
    [int]$StopTimeout  = 30,
    [int]$StartTimeout = 60
)

$ErrorActionPreference = "Stop"
$log     = Join-Path $RepoDir "logs\engine-$AccountKey.log"
$pidFile = Join-Path $RepoDir "logs\engine-$AccountKey.pid"
$clock   = [Diagnostics.Stopwatch]::StartNew()

function Step { param([string]$Text) Write-Host ("[{0,5:0.0}s] {1}" -f $clock.Elapsed.TotalSeconds, $Text) }

function Wait-Until {
    param([scriptblock]$Condition, [int]$TimeoutSeconds, [string]$What, [int]$PollMs = 400)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (& $Condition) { return $true }
        Start-Sleep -Milliseconds $PollMs
    }
    Step "  timed out after ${TimeoutSeconds}s waiting for: $What"
    return $false
}

function Get-RepoPython {
    # Only pythons from THIS repo's venv, so an unrelated python on the box
    # cannot break the elimination below. .Path throws for a process this session
    # cannot open, and $ErrorActionPreference = "Stop" would turn that into an
    # aborted restart - hence the per-process guard.
    $exe = Join-Path $RepoDir ".venv\Scripts\python.exe"
    Get-Process python -ErrorAction SilentlyContinue |
        Where-Object { try { $_.Path -eq $exe } catch { $false } }
}

function Read-EnginePid {
    # Trust the file only while its claim holds: alive, a python, and started
    # around when the file was written. Windows recycles pids, and a stale file
    # must never aim Stop-Process at an unrelated process.
    if (-not (Test-Path $pidFile)) { return 0 }
    $lines = @(Get-Content $pidFile -ErrorAction SilentlyContinue)
    if ($lines.Count -lt 1) { return 0 }
    $id = 0
    if (-not [int]::TryParse($lines[0].Trim(), [ref]$id)) { return 0 }

    $proc = Get-Process -Id $id -ErrorAction SilentlyContinue
    if (-not $proc) { Step "  pid file names $id, but nothing is running under it (stale)"; return 0 }
    if ($proc.ProcessName -ne 'python') {
        Step "  pid $id is '$($proc.ProcessName)', not python - refusing it (recycled pid)"
        return 0
    }
    if ($lines.Count -ge 2) {
        $stamp = [datetime]::MinValue
        if ([datetime]::TryParse($lines[1].Trim(), [ref]$stamp)) {
            $delta = ($stamp.ToUniversalTime() - $proc.StartTime.ToUniversalTime()).TotalSeconds
            if ($delta -lt -60 -or $delta -gt 600) {
                Step "  pid $id started ${delta}s from what the pid file claims - refusing it"
                return 0
            }
        }
    }
    return $id
}

function Show-Candidates {
    Write-Host ""
    Write-Host "engine python processes currently running (from $RepoDir\.venv):"
    Get-RepoPython |
        ForEach-Object {
            [PSCustomObject]@{
                Id = $_.Id
                Started = $_.StartTime
                RunningFor = "{0:hh\:mm\:ss}" -f ((Get-Date) - $_.StartTime)
            }
        } | Sort-Object Started | Format-Table -AutoSize
    Write-Host "Pid files present:"
    Get-ChildItem (Join-Path $RepoDir "logs\*.pid") -ErrorAction SilentlyContinue |
        ForEach-Object { "  $($_.Name): $((Get-Content $_.FullName)[0])" }
}

function Resolve-ByElimination {
    # Deduction, not a guess: if the OTHER engines have positively identified
    # themselves and exactly one venv python is left over, that one is ours. Two
    # candidates means we do not know, and this returns 0 rather than pick.
    $claimed = @()
    $stale = 0
    Get-ChildItem (Join-Path $RepoDir "logs\*.pid") -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -ne "engine-$AccountKey.pid" } |
        ForEach-Object {
            $first = @(Get-Content $_.FullName -ErrorAction SilentlyContinue)[0]
            $n = 0
            if ($first -and [int]::TryParse($first.Trim(), [ref]$n)) {
                if (Get-Process -Id $n -ErrorAction SilentlyContinue) {
                    $claimed += $n
                    Step "  $($_.Name) claims pid $n"
                } else {
                    # A hard kill skips Python's atexit, so the file outlives the
                    # process; and it is not written for the first several seconds
                    # of a restart while MetaTrader5 imports.
                    $stale++
                    Step "  $($_.Name) claims pid $n, which is NOT running (stale)"
                }
            }
        }
    if ($claimed.Count -eq 0) {
        if ($stale) { Step "  every other pid file is stale, so nothing can be eliminated" }
        return 0
    }

    $left = @(Get-RepoPython | Where-Object { $claimed -notcontains $_.Id })
    if ($left.Count -eq 1) {
        Step "  one python is unaccounted for after the other engines named themselves"
        return $left[0].Id
    }
    Step "  $($left.Count) unclaimed python processes - cannot deduce which is ours"
    return 0
}

# ---------------------------------------------------------------- identify ---
# $targetPid, never $enginePid: PowerShell identifiers are case-INSENSITIVE, so a
# local named $enginePid IS the -EnginePid parameter and silently discards
# whatever the caller passed.
Step "Identifying the live engine..."
$targetPid = 0
if ($EnginePid -gt 0) {
    # A hand-typed pid is the one input that can stop the wrong engine, and the
    # table it was copied from may be minutes stale. Check it harder.
    $given = Get-RepoPython | Where-Object { $_.Id -eq $EnginePid }
    if (-not $given) {
        Write-Host ""
        Write-Host "-EnginePid $EnginePid is not a running engine python from $RepoDir\.venv." -ForegroundColor Red
        Write-Host "It may have been restarted since you read it. Current candidates:" -ForegroundColor Red
        Show-Candidates
        exit 2
    }
    $claimedElsewhere = Get-ChildItem (Join-Path $RepoDir "logs\*.pid") -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -ne "engine-$AccountKey.pid" } |
        Where-Object { @(Get-Content $_.FullName -ErrorAction SilentlyContinue)[0].Trim() -eq "$EnginePid" }
    if ($claimedElsewhere) {
        Write-Host ""
        Write-Host "REFUSING: pid $EnginePid is claimed by $($claimedElsewhere.Name) - that is ANOTHER" -ForegroundColor Red
        Write-Host "account's engine. Stopping it would silently halt that lab." -ForegroundColor Red
        exit 1
    }
    $targetPid = $EnginePid
    Step "  using -EnginePid $targetPid as given (running since $($given.StartTime))"
} else {
    $targetPid = Read-EnginePid
    if ($targetPid -le 0) { $targetPid = Resolve-ByElimination }
}

if ($targetPid -le 0) {
    Write-Host ""
    Write-Host "Cannot identify the live engine: no usable $pidFile." -ForegroundColor Yellow
    Write-Host "Refusing to guess - the demo lab runs an identical command line, and stopping" -ForegroundColor Yellow
    Write-Host "the wrong one silently halts the lab. In the table below the LIVE engine is" -ForegroundColor Yellow
    Write-Host "normally the one running LONGEST. Check, then re-run with -EnginePid <id>." -ForegroundColor Yellow
    Show-Candidates
    exit 2
}
Step "Live engine is pid $targetPid"

# -------------------------------------------------------------------- stop ---
Step "Stopping $TaskName..."
Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
Step "Stopping engine pid $targetPid..."
Stop-Process -Id $targetPid -Force -ErrorAction SilentlyContinue

$gone = Wait-Until {
    -not (Get-Process -Id $targetPid -ErrorAction SilentlyContinue)
} $StopTimeout "engine pid $targetPid to exit"

if (-not $gone) {
    Write-Host ""
    Write-Host "ABORTED: pid $targetPid is still running. Starting the task now would put" -ForegroundColor Red
    Write-Host "TWO engines on the live account." -ForegroundColor Red
    exit 1
}
Step "Engine stopped."

# Task Scheduler can still report 'Running' just after its process is gone, and
# Start-ScheduledTask on a Running task is silently DROPPED under
# MultipleInstances=IgnoreNew - the command succeeds and nothing starts.
Step "Waiting for Task Scheduler to release '$TaskName'..."
$null = Wait-Until {
    (Get-ScheduledTask -TaskName $TaskName).State -ne 'Running'
} $StopTimeout "Task Scheduler to release '$TaskName'"

# ------------------------------------------------------------------- start ---
# Clearing the pid file first makes its REAPPEARANCE the proof that a new engine
# came up, rather than something inferred from a log line that may predate it.
Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
$logLinesBefore = 0
if (Test-Path $log) { $logLinesBefore = @(Get-Content $log).Count }

Step "Starting $TaskName..."
Start-ScheduledTask -TaskName $TaskName

# Watch for the engine EXITING as well as appearing: a crash after startup
# deletes the pid file again on the way out, so "no new pid" would otherwise be
# indistinguishable from a slow start and cost the full timeout.
$script:died = $false
$up = Wait-Until {
    $script:newPid = Read-EnginePid
    if ($script:newPid -gt 0 -and $script:newPid -ne $targetPid) { return $true }
    if ((Get-ScheduledTask -TaskName $TaskName).State -eq 'Ready') {
        $script:died = $true
        return $true
    }
    return $false
} $StartTimeout "the new engine to publish its pid" 1000

if ($script:died -or -not $up) {
    Write-Host ""
    if ($script:died) {
        Write-Host "FAILED: the engine STARTED and then exited - a crash, not a slow start." -ForegroundColor Red
    } else {
        Write-Host "FAILED: $TaskName did not bring an engine back up." -ForegroundColor Red
    }
    Write-Host "Task state:      $((Get-ScheduledTask -TaskName $TaskName).State)"
    Write-Host "Last run result: $((Get-ScheduledTaskInfo -TaskName $TaskName).LastTaskResult)"
    Write-Host "Reproduce it in a console to see the error directly:" -ForegroundColor Yellow
    Write-Host ("    {0}\.venv\Scripts\python.exe {0}\scripts\run_engine.py --env-file {0}\.env.live" -f $RepoDir) -ForegroundColor Yellow
    Write-Host "Tail of the log:"
    if (Test-Path $log) { Get-Content $log -Tail 25 | ForEach-Object { "    $_" } }
    exit 1
}
Step "New engine is pid $($script:newPid) - waiting for it to attach to the broker..."

# ------------------------------------------------------------------ verify ---
# Read only lines written since the restart began, so 'attached:' cannot be a
# leftover from the last run that worked.
$attached = $null
$null = Wait-Until {
    if (-not (Test-Path $log)) { return $false }
    $new = @(Get-Content $log) | Select-Object -Skip $logLinesBefore
    $script:attached = $new | Select-String -Pattern 'attached:' | Select-Object -Last 1
    return [bool]$script:attached
} $StartTimeout "the 'attached:' line for this restart" 1000

Write-Host ""
if ($attached) {
    Write-Host "OK - $($attached.Line.Trim())" -ForegroundColor Green
} else {
    Write-Host "Engine is up (pid $($script:newPid)) but has not logged 'attached:' yet - check $log" -ForegroundColor Yellow
}

Show-Candidates
Step "Done."
