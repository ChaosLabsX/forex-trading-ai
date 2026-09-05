<#
Restart the LIVE engine (ForexAI-Engine-Live) without leaving an orphan behind.

WHY THIS EXISTS. `Stop-ScheduledTask` ends the TASK - the powershell.exe running
run-live-engine.ps1 - but not the python.exe that wrapper already launched. The
python is reparented, keeps polling, keeps heartbeating, and keeps holding its
MT5 connection. Start the task again and you now have TWO live engines on one
account.

That happened on 2026-09-05 and was caught in the data, not the console: the
icmarkets-live heartbeat gaps went from a clean ~61s to 20/41/20/40s - the
signature of two engines on 61s cycles, offset from each other. Nothing had
traded yet, and the orphan could not trade (it started before
LIVE_TRADING_ENABLED was set, and environment is read once at process start), so
it was luck rather than design that nothing was double-placed.

THE ORDERING THAT MATTERS. The obvious fix - stop the task, then kill the
wrapper's children - does not work, because by then the wrapper is dead and its
children have been reparented, so there is nothing left to match on. This script
walks the descendant tree FIRST, then stops the task, then kills whatever of
that tree survived.

WHY NOT JUST KILL EVERY python.exe RUNNING run_engine.py. Because the DEMO lab
runs the identical command line - `.venv\Scripts\python.exe scripts\run_engine.py`
- so command-line matching cannot tell them apart, and killing the wrong one
silently stops the demo lab that is accumulating the 100 trades a readiness
verdict needs. Parentage can tell them apart: the demo task executes python.exe
directly (parent = Task Scheduler), while the live engine is always a descendant
of a powershell running run-live-engine.ps1. That is the only reliable
discriminator, and it is why this script is fussy about process trees instead of
names.

IT MUST NOT LOOK HUNG. The first version spent 30 seconds in unconditional
Start-Sleep and printed nothing while it did - and on 2026-09-05 it was
interrupted partway, which left the live engine untouched while the demo one
restarted normally. Every step now prints as it happens with an elapsed clock,
every wait is a poll against a real condition with a deadline, and the process
queries are WMI-filtered rather than enumerating all ~300 processes twice a
second.

IT MUST NOT LIE ABOUT SUCCEEDING. The first version "verified" by printing the
last 'attached:' line in the log - the last one EVER written - so a restart that
never happened still printed a success line from the previous run. The log is
now read only from the point this restart began.

THE SILENT FAILURE THIS GUARDS AGAINST. Task Scheduler can still consider a task
'Running' for a moment after its process is gone, and `Start-ScheduledTask` on a
Running task is silently ignored under MultipleInstances=IgnoreNew - the command
succeeds, nothing starts, and you get a demo engine that restarted and a live
engine that did not. The task is polled down to a non-Running state first, and
the start is verified rather than assumed.

Usage (elevated PowerShell on the VPS):
    powershell -NoProfile -ExecutionPolicy Bypass -File C:\ForexAI\infra\restart-live-engine.ps1
#>

param(
    [string]$TaskName = "ForexAI-Engine-Live",
    [string]$RepoDir  = "C:\ForexAI",
    # Deadlines, not durations: each wait returns the moment its condition is
    # met, and only runs this long when something is actually wrong.
    [int]$StopTimeout  = 20,
    [int]$StartTimeout = 45
)

$ErrorActionPreference = "Stop"
$log = Join-Path $RepoDir "logs\engine-icmarkets-live.log"
$clock = [Diagnostics.Stopwatch]::StartNew()

function Step { param([string]$Text) Write-Host ("[{0,5:0.0}s] {1}" -f $clock.Elapsed.TotalSeconds, $Text) }

function Wait-Until {
    param([scriptblock]$Condition, [int]$TimeoutSeconds, [string]$What, [int]$PollMs = 500)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (& $Condition) { return $true }
        Start-Sleep -Milliseconds $PollMs
    }
    Step "  timed out after ${TimeoutSeconds}s waiting for: $What"
    return $false
}

function Get-EngineProcs {
    # ONE WMI-filtered query. Enumerating every process costs ~3x this and was
    # being run twice a second by the polling loops.
    Get-CimInstance Win32_Process -Filter "Name='powershell.exe' OR Name='python.exe'"
}

function Get-LiveTree {
    # The run-live-engine.ps1 wrapper plus every descendant of it. The chain is
    # powershell -> python, so restricting the search to engine-shaped processes
    # loses nothing and keeps this cheap enough to poll.
    param($Procs = (Get-EngineProcs))
    $roots = @(($Procs | Where-Object {
        $_.Name -eq 'powershell.exe' -and $_.CommandLine -like '*run-live-engine.ps1*'
    }).ProcessId)
    if (-not $roots) { return @() }
    $tree = @($roots | Where-Object { $_ })
    $i = 0
    while ($i -lt $tree.Count) {
        $tree += @(($Procs | Where-Object { $_.ParentProcessId -eq $tree[$i] }).ProcessId)
        $i++
    }
    return @($tree | Sort-Object -Unique | Where-Object { $_ })
}

function Get-LivePython {
    # A live-engine python: descended from the wrapper, or orphaned from one.
    # The demo engine never matches - its parent is Task Scheduler, always alive.
    $procs = Get-EngineProcs
    $tree = Get-LiveTree -Procs $procs
    $procs | Where-Object {
        $_.Name -eq 'python.exe' -and $_.CommandLine -like '*run_engine*'
    } | Where-Object {
        ($tree -contains $_.ProcessId) -or
        (-not (Get-Process -Id $_.ParentProcessId -ErrorAction SilentlyContinue))
    }
}

# 1. Snapshot the tree BEFORE anything is stopped. Once the wrapper dies its
#    children are reparented and this mapping is gone.
Step "Looking for the live engine..."
$tree = Get-LiveTree
$doomed = @((Get-LivePython).ProcessId)
if ($tree.Count) {
    Step "Live engine process tree: $($tree -join ', ')"
} else {
    Step "No running live-engine wrapper found (already stopped, or started another way)."
}

# 2. Stop the task, then clean up anything the stop left running.
Step "Stopping $TaskName..."
Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue

foreach ($id in $tree) {
    # Re-verify before killing: a PID can be recycled between the snapshot and
    # here, and this script runs elevated.
    $p = Get-CimInstance Win32_Process -Filter "ProcessId=$id" -ErrorAction SilentlyContinue
    if ($p -and ($p.Name -eq 'python.exe' -or $p.CommandLine -like '*run-live-engine.ps1*')) {
        Stop-Process -Id $id -Force -ErrorAction SilentlyContinue
        Step "  stopped $id ($($p.Name))"
        $doomed += $id
    }
}

# 3. Orphan sweep, then confirm the account really is clear. Starting a second
#    engine on top of a survivor is the exact bug this script exists to prevent,
#    so this is a hard gate, not a courtesy check.
Get-LivePython | ForEach-Object {
    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    Step "  stopped orphan $($_.ProcessId)"
    $doomed += $_.ProcessId
}

$doomed = @($doomed | Sort-Object -Unique | Where-Object { $_ })
if ($doomed.Count) {
    Step "Waiting for PID(s) $($doomed -join ', ') to exit..."
    # Poll the specific PIDs rather than re-scanning: a targeted liveness check
    # is several times cheaper, which matters at 2 polls a second.
    $gone = Wait-Until {
        -not ($doomed | Where-Object { Get-Process -Id $_ -ErrorAction SilentlyContinue })
    } $StopTimeout "the old live engine to exit"

    if (-not $gone) {
        Write-Host ""
        Write-Host "ABORTED: a live-engine process is still running, so starting the task now" -ForegroundColor Red
        Write-Host "would put TWO engines on the live account. Survivors:" -ForegroundColor Red
        Get-LivePython | Format-Table ProcessId, ParentProcessId, CreationDate -AutoSize
        exit 1
    }
}

# Task Scheduler can lag behind its own process. Starting while it still reads
# Running is silently dropped under MultipleInstances=IgnoreNew.
Step "Waiting for Task Scheduler to release '$TaskName'..."
$null = Wait-Until {
    (Get-ScheduledTask -TaskName $TaskName).State -ne 'Running'
} $StopTimeout "Task Scheduler to release '$TaskName'"

# 4. Start, and read the log only from here on - so the evidence below belongs
#    to THIS restart and not to the last one that worked.
$logLinesBefore = 0
if (Test-Path $log) { $logLinesBefore = @(Get-Content $log).Count }

Step "Starting $TaskName..."
Start-ScheduledTask -TaskName $TaskName

$up = Wait-Until { @(Get-LivePython).Count -ge 1 } $StartTimeout "the engine process to appear" 1000
if (-not $up) {
    Write-Host ""
    Write-Host "FAILED: $TaskName did not produce an engine process." -ForegroundColor Red
    Write-Host "Task state:      $((Get-ScheduledTask -TaskName $TaskName).State)"
    Write-Host "Last run result: $((Get-ScheduledTaskInfo -TaskName $TaskName).LastTaskResult)"
    Write-Host "Check the tail of $log, then try: Start-ScheduledTask -TaskName $TaskName"
    exit 1
}
Step "Engine process is up - waiting for it to attach to the broker..."

# 5. Prove it came back on the RIGHT account. A wrong-account attach is worse
#    than a failed start, so this waits for the line rather than assuming it.
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
    Write-Host "Engine is running but has not logged 'attached:' yet - check $log" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Engine processes now running (expect ONE live tree plus the demo pair):"
Get-EngineProcs |
    Where-Object { $_.CommandLine -match 'run_engine|run-live-engine' } |
    ForEach-Object {
        $q = Get-Process -Id $_.ParentProcessId -ErrorAction SilentlyContinue
        [PSCustomObject]@{
            PID = $_.ProcessId; PPID = $_.ParentProcessId
            ParentAlive = [bool]$q; Started = $_.CreationDate; Proc = $_.Name
        }
    } | Sort-Object Started | Format-Table -AutoSize

Step "Done."
