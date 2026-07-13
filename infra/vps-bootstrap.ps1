<#
Run this on the VPS itself (via RDP), in an Administrator PowerShell window.
Installs Python + Git, clones the repo, sets up the venv and dependencies.

Does NOT touch MT5 (GUI installer, needs your own login - see vps-setup.md)
and does NOT write any secrets - .env is a separate manual step so real
credentials never need to pass through a script.
#>

$ErrorActionPreference = "Stop"
$RepoDir = "C:\ForexAI"
$RepoUrl = "https://github.com/ChaosLabsX/forex-trading-ai.git"

$hasWinget = [bool](Get-Command winget -ErrorAction SilentlyContinue)
Write-Host "winget available: $hasWinget"

function Install-Tool {
    param(
        [string]$WingetId,
        [string]$Name,
        [string]$FallbackUrl,
        [string]$FallbackArgs,
        [string]$FallbackFile
    )
    if (Get-Command $Name.ToLower() -ErrorAction SilentlyContinue) {
        Write-Host "$Name already installed, skipping."
        return
    }
    if ($script:hasWinget) {
        Write-Host "Installing $Name via winget..."
        winget install --id $WingetId --silent --accept-package-agreements --accept-source-agreements
    } else {
        Write-Host "winget not found - downloading the $Name installer directly..."
        $dest = Join-Path $env:TEMP $FallbackFile
        Invoke-WebRequest -Uri $FallbackUrl -OutFile $dest
        Start-Process -FilePath $dest -ArgumentList $FallbackArgs -Wait
        Remove-Item $dest -Force -ErrorAction SilentlyContinue
    }
}

Write-Host "`n== Installing Python 3.12 =="
Install-Tool -WingetId "Python.Python.3.12" -Name "python" `
    -FallbackUrl "https://www.python.org/ftp/python/3.12.7/python-3.12.7-amd64.exe" `
    -FallbackArgs "/quiet InstallAllUsers=1 PrependPath=1" -FallbackFile "python-installer.exe"

Write-Host "`n== Installing Git =="
Install-Tool -WingetId "Git.Git" -Name "git" `
    -FallbackUrl "https://github.com/git-for-windows/git/releases/latest/download/Git-64-bit.exe" `
    -FallbackArgs "/VERYSILENT /NORESTART" -FallbackFile "git-installer.exe"

Write-Host "`n== Refreshing PATH for this session =="
$env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
            [System.Environment]::GetEnvironmentVariable("Path", "User")

Write-Host "`n== Getting the repo (public - no credentials needed) =="
if (Test-Path $RepoDir) {
    Write-Host "$RepoDir already exists - pulling latest instead of cloning."
    Push-Location $RepoDir
    git pull
    Pop-Location
} else {
    git clone $RepoUrl $RepoDir
}

Write-Host "`n== Setting up the Python venv =="
Push-Location $RepoDir
python -m venv .venv
& ".venv\Scripts\python.exe" -m pip install --upgrade pip
& ".venv\Scripts\python.exe" -m pip install -e .
Pop-Location

Write-Host "`n== Hardening Windows Firewall (safe to automate - no secrets, additive only) =="
Set-NetFirewallProfile -Profile Domain,Public,Private -Enabled True
Write-Host "Current inbound allow rules (should just be RDP unless you've added more):"
Get-NetFirewallRule -Direction Inbound -Enabled True |
    Where-Object { $_.Action -eq "Allow" } |
    Format-Table DisplayName, Profile

Write-Host "`n== Done =="
Write-Host "Next (manual - see infra/vps-setup.md for details):"
Write-Host "  1. Install the IC Markets MT5 terminal, log into ICMarketsSC-Demo, enable Algo Trading."
Write-Host "  2. Run netplwiz to configure Windows auto-login for this account."
Write-Host "  3. Paste-run the second script (has your real secrets - given directly in chat, not in this repo)."
Write-Host "     It writes .env, creates the MT5 startup shortcut, and registers + starts the engine task."
