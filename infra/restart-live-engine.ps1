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

Usage (elevated PowerShell on the VPS):
    powershell -NoProfile -ExecutionPolicy Bypass -File C:\ForexAI\infra\restart-live-engine.ps1
#>

param(
    [string]$TaskName = "ForexAI-Engine-Live",
    [string]$RepoDir  = "C:\ForexAI",
    [int]$SettleSeconds = 25
)

$ErrorActionPreference = "Stop"

# 1. Snapshot the tree BEFORE anything is stopped. Once the wrapper dies its
#    children are reparented and this mapping is gone.
$roots = @((Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" |
            Where-Object { $_.CommandLine -like '*run-live-engine.ps1*' }).ProcessId)

$all  = Get-CimInstance Win32_Process
$tree = @($roots | Where-Object { $_ })
$i = 0
while ($i -lt $tree.Count) {
    $tree += @(($all | Where-Object { $_.ParentProcessId -eq $tree[$i] }).ProcessId)
    $i++
}
$tree = @($tree | Sort-Object -Unique | Where-Object { $_ })

if ($tree.Count) {
    Write-Host "Live engine process tree: $($tree -join ', ')"
} else {
    Write-Host "No running live-engine wrapper found (already stopped, or started another way)."
}

# 2. Stop the task, then clean up anything the stop left running.
Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
Start-Sleep -Seconds 3

foreach ($id in $tree) {
    # Re-verify before killing: a PID can be recycled between the snapshot and
    # here, and this script runs elevated.
    $p = Get-CimInstance Win32_Process -Filter "ProcessId=$id" -ErrorAction SilentlyContinue
    if ($p -and ($p.Name -eq 'python.exe' -or $p.CommandLine -like '*run-live-engine.ps1*')) {
        Stop-Process -Id $id -Force -ErrorAction SilentlyContinue
        Write-Host "  stopped $id ($($p.Name))"
    }
}

# 3. Orphan sweep: a live-engine python whose parent no longer exists. The demo
#    engine never matches - its parent is Task Scheduler, which is always alive.
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -like '*run_engine*' } |
    Where-Object { -not (Get-Process -Id $_.ParentProcessId -ErrorAction SilentlyContinue) } |
    ForEach-Object {
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        Write-Host "  stopped orphan $($_.ProcessId)"
    }

Start-Sleep -Seconds 2
Start-ScheduledTask -TaskName $TaskName
Write-Host "Started $TaskName - waiting ${SettleSeconds}s for it to attach..."
Start-Sleep -Seconds $SettleSeconds

# 4. Prove it came back on the right account, and that there is exactly one.
$log = Join-Path $RepoDir "logs\engine-icmarkets-live.log"
if (Test-Path $log) {
    Select-String -Path $log -Pattern 'attached:' | Select-Object -Last 1
}

Write-Host ""
Write-Host "Engine processes now running (expect ONE live tree plus the demo pair):"
Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='powershell.exe'" |
    Where-Object { $_.CommandLine -match 'run_engine|run-live-engine' } |
    ForEach-Object {
        $q = Get-Process -Id $_.ParentProcessId -ErrorAction SilentlyContinue
        [PSCustomObject]@{
            PID = $_.ProcessId; PPID = $_.ParentProcessId
            ParentAlive = [bool]$q; Started = $_.CreationDate; Proc = $_.Name
        }
    } | Sort-Object Started | Format-Table -AutoSize
