<#
Restart the LIVE engine (ForexAI-Engine-Live) without leaving an orphan behind.

WHY THIS EXISTS. `Stop-ScheduledTask` ends the TASK - the powershell.exe running
run-live-engine.ps1 - but not the python.exe that wrapper already launched. The
python is reparented, keeps polling, keeps heartbeating, and keeps holding its
MT5 connection. Start the task again and you now have TWO live engines on one
account. That happened on 2026-09-05: icmarkets-live heartbeat gaps went from a
clean ~61s to 20/41/20/40s, the signature of two engines on 61s cycles offset
from each other.

WHY IT NO LONGER USES WMI. Telling the live engine apart from the demo lab is
genuinely hard by inspection - both are `.venv\Scripts\python.exe
scripts\run_engine.py`, so a command-line match cannot separate them, and
killing the wrong one stops the lab that is accumulating the 100 trades a
readiness verdict needs. The first two versions of this script solved that by
walking the process tree through `Get-CimInstance Win32_Process`. That is
correct and it is also unusable: on this VPS the query does not come back in any
reasonable time, and the script hung on its FIRST statement, twice, before
stopping anything at all. A restart script that hangs before it acts is a
restart script that does not restart anything.

So the engine now says who it is. scripts/run_engine.py writes its own PID to
logs\engine-<account>.pid at startup and removes it on a clean exit. Reading a
file is instant, exact, and cannot confuse the two accounts - each writes its
own. Everything here is Get-Process and file I/O; there is no WMI left.

That also gives a real success signal. This script deletes the pid file, starts
the task, and waits for a NEW pid to appear. A new pid is proof the engine came
back. The previous version inferred success from the last 'attached:' line in
the log - the last one EVER written - so a restart that never happened still
printed a success line from the run before it.

FIRST RUN AFTER THIS CHANGE. The engine currently running was started before any
of this existed, so it has no pid file. The script will say so and list the
python processes it can see, with how long each has been running, and stop. Pass
the live one explicitly:

    ... -EnginePid <id>

It refuses to guess rather than risk stopping the demo lab.

Usage (elevated PowerShell on the VPS):
    powershell -NoProfile -ExecutionPolicy Bypass -File C:\ForexAI\infra\restart-live-engine.ps1
#>

param(
    [string]$TaskName = "ForexAI-Engine-Live",
    [string]$RepoDir  = "C:\ForexAI",
    [string]$AccountKey = "icmarkets-live",
    # Escape hatch for the first run, or any time the pid file is missing.
    [int]$EnginePid = 0,
    # Deadlines, not durations: each wait returns the moment its condition is
    # met, and only runs this long when something is actually wrong.
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

function Read-EnginePid {
    # Returns the PID only if the file's claim still holds: alive, a python, and
    # started around when the file was written. Windows recycles PIDs, and a
    # stale file must never aim Stop-Process at an unrelated process.
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
            # The file is written seconds after start; allow generous slack, but
            # reject a process that clearly predates or postdates the claim.
            $delta = ($stamp.ToUniversalTime() - $proc.StartTime.ToUniversalTime()).TotalSeconds
            if ($delta -lt -60 -or $delta -gt 600) {
                Step "  pid $id started ${delta}s from what the pid file claims - refusing it"
                return 0
            }
        }
    }
    return $id
}

function Get-RepoPython {
    # Only pythons running from THIS repo's venv. `Get-Process python` alone is
    # too broad - any unrelated python on the box (a tool, an installer, a
    # scratch script) would be counted, and the elimination below needs its
    # candidate set to be exactly the engines. Process.Path is a plain .NET
    # property, so this stays WMI-free.
    #
    # .Path reads MainModule.FileName, which THROWS for a process this session
    # cannot open. With $ErrorActionPreference = "Stop" at script scope, one
    # unreadable python anywhere on the box would abort the whole restart - so
    # each read is guarded individually and an unreadable process is simply not
    # a candidate.
    $exe = Join-Path $RepoDir ".venv\Scripts\python.exe"
    Get-Process python -ErrorAction SilentlyContinue |
        Where-Object { try { $_.Path -eq $exe } catch { $false } }
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
    # Not a guess: if the OTHER engines have each positively identified
    # themselves by pid file, and exactly one python is left over, that one is
    # ours by deduction. Requires exactly one survivor - two candidates means we
    # do not know, and this returns 0 rather than pick.
    $claimed = @()
    Get-ChildItem (Join-Path $RepoDir "logs\*.pid") -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -ne "engine-$AccountKey.pid" } |
        ForEach-Object {
            $first = @(Get-Content $_.FullName -ErrorAction SilentlyContinue)[0]
            $n = 0
            if ($first -and [int]::TryParse($first.Trim(), [ref]$n)) {
                $claimed += $n
                Step "  $($_.Name) claims pid $n"
            }
        }
    if ($claimed.Count -eq 0) { return 0 }

    $left = @(Get-RepoPython | Where-Object { $claimed -notcontains $_.Id })
    if ($left.Count -eq 1) {
        Step "  one python is unaccounted for after the other engines named themselves"
        return $left[0].Id
    }
    Step "  $($left.Count) unclaimed python processes - cannot deduce which is ours"
    return 0
}

# ---------------------------------------------------------------- identify ---
Step "Identifying the live engine..."
$enginePid = 0
if ($EnginePid -gt 0) {
    $enginePid = $EnginePid
    Step "  using -EnginePid $enginePid as given"
} else {
    $enginePid = Read-EnginePid
    if ($enginePid -le 0) { $enginePid = Resolve-ByElimination }
}

if ($enginePid -le 0) {
    Write-Host ""
    Write-Host "Cannot identify the live engine: no usable $pidFile." -ForegroundColor Yellow
    Write-Host "This is expected the first time, for an engine started before it wrote one." -ForegroundColor Yellow
    Write-Host "Refusing to guess - the demo lab runs an identical command line, and stopping" -ForegroundColor Yellow
    Write-Host "the wrong one silently halts the lab. Re-run naming the live engine:" -ForegroundColor Yellow
    Write-Host "    powershell -NoProfile -ExecutionPolicy Bypass -File $PSCommandPath -EnginePid <id>" -ForegroundColor Yellow
    Show-Candidates
    exit 2
}
Step "Live engine is pid $enginePid"

# -------------------------------------------------------------------- stop ---
Step "Stopping $TaskName (ends the run-live-engine.ps1 wrapper)..."
Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue

# The wrapper dying does NOT take the python with it - that is the whole bug.
Step "Stopping engine pid $enginePid..."
Stop-Process -Id $enginePid -Force -ErrorAction SilentlyContinue

$gone = Wait-Until {
    -not (Get-Process -Id $enginePid -ErrorAction SilentlyContinue)
} $StopTimeout "engine pid $enginePid to exit"

if (-not $gone) {
    Write-Host ""
    Write-Host "ABORTED: pid $enginePid is still running. Starting the task now would put" -ForegroundColor Red
    Write-Host "TWO engines on the live account, which is the bug this script exists to stop." -ForegroundColor Red
    exit 1
}
Step "Engine stopped."

# Task Scheduler can still report 'Running' briefly after its process is gone,
# and Start-ScheduledTask on a Running task is silently DROPPED under
# MultipleInstances=IgnoreNew - the command succeeds and nothing starts.
Step "Waiting for Task Scheduler to release '$TaskName'..."
$null = Wait-Until {
    (Get-ScheduledTask -TaskName $TaskName).State -ne 'Running'
} $StopTimeout "Task Scheduler to release '$TaskName'"

# ------------------------------------------------------------------- start ---
# Clear the pid file first: its REAPPEARANCE with a different pid is the proof
# that the new engine actually came up, rather than something inferred.
Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
$logLinesBefore = 0
if (Test-Path $log) { $logLinesBefore = @(Get-Content $log).Count }

Step "Starting $TaskName..."
Start-ScheduledTask -TaskName $TaskName

$newPid = 0
$up = Wait-Until {
    $script:newPid = Read-EnginePid
    return ($script:newPid -gt 0 -and $script:newPid -ne $enginePid)
} $StartTimeout "the new engine to publish its pid" 1000

if (-not $up) {
    Write-Host ""
    Write-Host "FAILED: $TaskName did not bring an engine back up." -ForegroundColor Red
    Write-Host "Task state:      $((Get-ScheduledTask -TaskName $TaskName).State)"
    Write-Host "Last run result: $((Get-ScheduledTaskInfo -TaskName $TaskName).LastTaskResult)"
    Write-Host "Tail of the log:"
    if (Test-Path $log) { Get-Content $log -Tail 20 | ForEach-Object { "    $_" } }
    exit 1
}
Step "New engine is pid $newPid - waiting for it to attach to the broker..."

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
    Write-Host "Engine is up (pid $newPid) but has not logged 'attached:' yet - check $log" -ForegroundColor Yellow
}

Show-Candidates
Step "Done."
