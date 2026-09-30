<#
.SYNOPSIS
    Stop the HireBuddha stack on a Windows development machine.

.DESCRIPTION
    Windows counterpart of stop_services.sh, for LOCAL DEVELOPMENT ONLY. The test
    and production environments are Ubuntu VMs on GCP and use stop_services.sh.

    Stops, in order: the Vite frontend (port 3000), both Arq workers, the API
    (port 8000) - and a retired Unified Gateway still on port 8001, if one is
    found - then PostgreSQL and Redis (docker compose stop; the containers and
    the database volume are kept).

    Each service is found by the PID file start_services.ps1 wrote in logs\, then
    by its port or command line, so a service started some other way (an IDE, a
    terminal) is stopped too. A process is stopped only if its command line is
    the expected one: something else holding port 3000 or 8000 is reported and
    left running. Every stop ends the whole process tree (cmd.exe, the venv
    launcher, uvicorn's reloader, npm and vite).

    Stops are forceful (taskkill /F): a hidden console process cannot be asked to
    shut down on Windows. A job a worker is running is cut off, and the worker's
    heartbeat stays on /api/v1/health for up to 30 s instead of leaving at once.

.PARAMETER Only
    Stop only these services: frontend, workers, api, docker (comma-separated).
    Default: all four.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\stop_services.ps1

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\stop_services.ps1 -Only workers

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\stop_services.ps1 -WhatIf
    Lists what would be stopped, and stops nothing.
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string[]]$Only = @("frontend", "workers", "api", "docker")
)

$ErrorActionPreference = "Continue"
$Cmdlet = $PSCmdlet

# Load the modules up front, outside -WhatIf: importing them under -WhatIf
# reports every alias they define as a "What if" line.
$whatIf = $WhatIfPreference
$WhatIfPreference = $false
Import-Module CimCmdlets, NetTCPIP
$WhatIfPreference = $whatIf

$Valid = @("frontend", "workers", "api", "docker")
# `-Only api,workers` arrives as one string under `powershell -File`.
$Services = @($Only | ForEach-Object { $_ -split "," } | ForEach-Object { $_.Trim().ToLower() } | Where-Object { $_ })
$Unknown = @($Services | Where-Object { $_ -notin $Valid })
if ($Unknown.Count -gt 0) {
    Write-Host "Unknown service(s): $($Unknown -join ', '). Choose from: $($Valid -join ', ')" -ForegroundColor Red
    exit 2
}

$Root = $PSScriptRoot
$BackendDir = Join-Path $Root "backend"
$LogDir = Join-Path $Root "logs"

# What each service's processes look like: the executables in its process tree,
# and a pattern its command lines match.
$Api = @{ Label = "API"; Names = @("cmd.exe", "python.exe"); Pattern = "uvicorn\s+src\.main:app" }
$Gateway = @{ Label = "retired Unified Gateway"; Names = @("cmd.exe", "python.exe"); Pattern = "uvicorn\s+src\.gateway\." }
$Frontend = @{ Label = "Frontend"; Names = @("cmd.exe", "node.exe"); Pattern = "vite|npm" }
$Worker = @{ Label = "Arq worker"; Names = @("cmd.exe", "python.exe"); Pattern = "-m arq src\.ai\.worker\.WorkerSettings(\s|$)" }
$ChildWorker = @{ Label = "Arq child-run worker"; Names = @("cmd.exe", "python.exe"); Pattern = "-m arq src\.ai\.worker\.ChildWorkerSettings(\s|$)" }

function Write-Step([string]$Text) { Write-Host $Text -ForegroundColor Cyan }
function Write-Ok([string]$Text) { Write-Host "  [ok]   $Text" -ForegroundColor Green }
function Write-Skip([string]$Text) { Write-Host "  [skip] $Text" -ForegroundColor Yellow }
function Write-Warn([string]$Text) { Write-Host "  [warn] $Text" -ForegroundColor Yellow }

function Get-Processes { @(Get-CimInstance Win32_Process) }

function Test-Service($Proc, $Service) {
    $Proc -and ($Service.Names -contains $Proc.Name) -and ($Proc.CommandLine -match $Service.Pattern)
}

function Get-TreeRoot($Proc, $Service, $All) {
    # Climb to the outermost ancestor that still belongs to the service, e.g. from
    # uvicorn's server process up to the cmd.exe that start_services.ps1 started.
    $current = $Proc
    while ($true) {
        $parent = $All | Where-Object { $_.ProcessId -eq $current.ParentProcessId } | Select-Object -First 1
        if (-not (Test-Service $parent $Service)) { return $current }
        $current = $parent
    }
}

$Handled = @{}   # PIDs already stopped (or, under -WhatIf, already listed)

function Stop-Tree([int]$Id, [string]$Label) {
    if ($Handled.ContainsKey($Id)) { return }
    $Handled[$Id] = $true
    if ($Cmdlet.ShouldProcess("$Label (PID $Id) and its child processes", "Stop")) {
        taskkill /PID $Id /T /F *> $null
        if ($LASTEXITCODE -eq 0) { Write-Ok "$Label stopped (PID $Id)" }
        else { Write-Warn "could not stop $Label (PID $Id); taskkill exit $LASTEXITCODE" }
    }
}

function Stop-FromPidFile($Service, [string]$LogName) {
    # Returns how many process trees it stopped (0 or 1).
    $file = Join-Path $LogDir "$LogName.pid"
    if (-not (Test-Path $file)) { return 0 }
    $id = 0
    [void][int]::TryParse((Get-Content $file -TotalCount 1), [ref]$id)
    $proc = Get-Processes | Where-Object { $_.ProcessId -eq $id } | Select-Object -First 1
    # A PID is reused once its process exits: stop it only if it is still the service.
    $stopped = 0
    if (Test-Service $proc $Service) {
        Stop-Tree $id $Service.Label
        $stopped = 1
    } else {
        Write-Skip "$($Service.Label) is not running under logs\$LogName.pid (stale PID file)"
    }
    if (-not $WhatIfPreference) { Remove-Item $file -Force }
    return $stopped
}

function Stop-Matching($Service) {
    # Every process tree whose command line is the service's, however it was started.
    $all = Get-Processes
    $roots = @($all | Where-Object { Test-Service $_ $Service } |
        ForEach-Object { Get-TreeRoot $_ $Service $all } | Sort-Object ProcessId -Unique |
        Where-Object { -not $Handled.ContainsKey([int]$_.ProcessId) })
    foreach ($root in $roots) { Stop-Tree $root.ProcessId $Service.Label }
    return $roots.Count
}

function Stop-Port([int]$Port, $Service) {
    $all = Get-Processes
    $owners = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique)
    foreach ($id in $owners) {
        $proc = $all | Where-Object { $_.ProcessId -eq $id } | Select-Object -First 1
        if (-not $proc) { continue }
        if (Test-Service $proc $Service) {
            Stop-Tree (Get-TreeRoot $proc $Service $all).ProcessId $Service.Label
        } else {
            Write-Warn "port $Port is held by $($proc.Name) (PID $id), which is not the $($Service.Label) - left running"
        }
    }
}

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  HireBuddha - Windows dev shutdown" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

# -- 1. Frontend -------------------------------------------------------------------
if ($Services -contains "frontend") {
    Write-Step "[1/4] Frontend (port 3000)"
    $null = Stop-FromPidFile $Frontend "frontend"
    Stop-Port 3000 $Frontend
}

# -- 2. Arq workers ----------------------------------------------------------------
if ($Services -contains "workers") {
    Write-Step "[2/4] Arq workers"
    foreach ($pair in @(@($Worker, "arq_worker"), @($ChildWorker, "arq_child_worker"))) {
        $stopped = (Stop-FromPidFile $pair[0] $pair[1]) + (Stop-Matching $pair[0])
        if ($stopped -eq 0) { Write-Skip "no $($pair[0].Label) running" }
    }
}

# -- 3. API (and a retired gateway) ------------------------------------------------
if ($Services -contains "api") {
    Write-Step "[3/4] API (port 8000)"
    $null = Stop-FromPidFile $Api "backend_api"
    Stop-Port 8000 $Api
    # The Unified Gateway on :8001 was merged into the API (2026-09-30); stop one
    # an older setup left running.
    $null = Stop-FromPidFile $Gateway "unified_gateway"
    Stop-Port 8001 $Gateway
}

# -- 4. PostgreSQL + Redis ---------------------------------------------------------
if ($Services -contains "docker") {
    Write-Step "[4/4] PostgreSQL + Redis (docker compose)"
    docker info *> $null
    if ($LASTEXITCODE -ne 0) {
        Write-Skip "Docker is not running"
    } elseif ($Cmdlet.ShouldProcess("docker compose services in backend\ (containers and data are kept)", "Stop")) {
        Push-Location $BackendDir
        docker compose stop
        $composeExit = $LASTEXITCODE
        Pop-Location
        if ($composeExit -eq 0) { Write-Ok "Docker services stopped (start again with .\start_services.ps1)" }
        else { Write-Warn "docker compose stop failed (exit $composeExit)" }
    }
}

Write-Host ""
Write-Host "Done. Start again with: .\start_services.ps1" -ForegroundColor Cyan
