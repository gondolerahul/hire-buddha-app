<#
.SYNOPSIS
    Start the HireBuddha stack on a Windows development machine.

.DESCRIPTION
    Windows counterpart of start_services.sh, for LOCAL DEVELOPMENT ONLY. The test
    and production environments are Ubuntu VMs on GCP and use start_services.sh.

    Starts, in order:
      1. PostgreSQL (host port 5433) and Redis (6379) with docker compose
      2. The API on port 8000 (uvicorn --reload): REST, webhooks, internal events
         and the media-stream WebSockets
      3. The two Arq workers: the main worker (default queue and the crons) and
         the child-run worker (queue "children")
      4. The Vite frontend on port 3000

    A service that is already running is left alone, so the script is safe to run
    again after one service stopped. Output goes to logs\<service>.log and each
    started process's PID to logs\<service>.pid - the same files start_services.sh
    uses. stop_services.ps1 stops everything again.

    The Arq workers do not reload on code changes. After a backend change run:
        .\stop_services.ps1 -Only workers; .\start_services.ps1 -Only workers

.PARAMETER Only
    Start only these services: docker, api, workers, frontend (comma-separated).
    Default: all four.

.PARAMETER Lan
    Bind the API to 0.0.0.0 instead of 127.0.0.1, e.g. to reach it from a phone
    running the mobile dialer. (Vite already listens on all interfaces.) Windows
    Firewall asks the first time.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\start_services.ps1

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\start_services.ps1 -Only api,workers
#>
[CmdletBinding()]
param(
    [string[]]$Only = @("docker", "api", "workers", "frontend"),
    [switch]$Lan
)

# Native tools (docker, npm) write progress to stderr; errors are checked through
# $LASTEXITCODE rather than letting Windows PowerShell turn stderr into exceptions.
$ErrorActionPreference = "Continue"

$Valid = @("docker", "api", "workers", "frontend")
# `-Only api,workers` arrives as one string under `powershell -File`.
$Services = @($Only | ForEach-Object { $_ -split "," } | ForEach-Object { $_.Trim().ToLower() } | Where-Object { $_ })
$Unknown = @($Services | Where-Object { $_ -notin $Valid })
if ($Unknown.Count -gt 0) {
    Write-Host "Unknown service(s): $($Unknown -join ', '). Choose from: $($Valid -join ', ')" -ForegroundColor Red
    exit 2
}

$Root = $PSScriptRoot
$BackendDir = Join-Path $Root "backend"
$FrontendDir = Join-Path $Root "frontend"
$LogDir = Join-Path $Root "logs"
$Python = ".venv\Scripts\python.exe"      # relative to backend\, so a path with spaces needs no quoting
$BindHost = if ($Lan) { "0.0.0.0" } else { "127.0.0.1" }

# Python on Windows defaults to the ANSI code page; the backend reads and logs UTF-8.
$env:PYTHONUTF8 = "1"

function Write-Step([string]$Text) { Write-Host $Text -ForegroundColor Cyan }
function Write-Ok([string]$Text) { Write-Host "  [ok]   $Text" -ForegroundColor Green }
function Write-Skip([string]$Text) { Write-Host "  [skip] $Text" -ForegroundColor Yellow }
function Write-Warn([string]$Text) { Write-Host "  [warn] $Text" -ForegroundColor Yellow }

function Test-Port([int]$Port) {
    [bool](Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
}

function Get-ArqWorker([string]$Settings) {
    # The venv launcher and the interpreter it starts both carry the command line.
    Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" |
        Where-Object { $_.CommandLine -match "-m arq src\.ai\.worker\.$Settings(\s|$)" }
}

function Start-Hidden([string]$Name, [string]$Dir, [string]$Command, [string]$LogName) {
    # cmd.exe runs the command so stdout and stderr share one log, as nohup does in
    # start_services.sh. The PID file holds cmd.exe's PID; stop_services.ps1 ends
    # the whole process tree under it.
    $log = Join-Path $LogDir "$LogName.log"
    $proc = Start-Process -FilePath "cmd.exe" -ArgumentList "/c $Command > `"$log`" 2>&1" `
        -WorkingDirectory $Dir -WindowStyle Hidden -PassThru -ErrorAction Stop
    Set-Content -Path (Join-Path $LogDir "$LogName.pid") -Value $proc.Id -Encoding ascii
    Write-Ok "$Name started (PID $($proc.Id)) - log: logs\$LogName.log"
    return $proc
}

function Wait-Until([string]$Name, [scriptblock]$Ready, $Proc = $null, [string]$LogName = "", [int]$Seconds = 90) {
    for ($i = 0; $i -lt $Seconds; $i++) {
        if (& $Ready) { Write-Ok "$Name is up"; return $true }
        if ($Proc -and $Proc.HasExited) { break }
        Start-Sleep -Seconds 1
    }
    Write-Warn "$Name did not come up."
    if ($LogName) {
        Write-Host "         Last lines of logs\$LogName.log:"
        Get-Content (Join-Path $LogDir "$LogName.log") -Tail 15 -ErrorAction SilentlyContinue |
            ForEach-Object { Write-Host "         $_" }
    }
    return $false
}

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  HireBuddha - Windows dev startup" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

if (-not (Test-Path (Join-Path $BackendDir ".env"))) {
    Write-Host "backend\.env not found. Copy backend\.env.example to backend\.env and fill it in." -ForegroundColor Red
    exit 1
}
if (($Services -contains "api" -or $Services -contains "workers") -and -not (Test-Path (Join-Path $BackendDir $Python))) {
    Write-Host "backend\$Python not found. Create the virtualenv and install the dependencies first (README)." -ForegroundColor Red
    exit 1
}
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

# -- 1. PostgreSQL + Redis ---------------------------------------------------------
if ($Services -contains "docker") {
    Write-Step "[1/4] PostgreSQL + Redis (docker compose)"
    docker info *> $null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  Docker is not running. Start Docker Desktop, then run this script again." -ForegroundColor Red
        exit 1
    }
    Push-Location $BackendDir
    docker compose up -d db redis
    $composeExit = $LASTEXITCODE
    Pop-Location
    if ($composeExit -ne 0) {
        Write-Host "  docker compose up failed (exit $composeExit)." -ForegroundColor Red
        exit 1
    }
    $null = Wait-Until "PostgreSQL" { docker exec hirebuddha-db pg_isready -U postgres *> $null; $LASTEXITCODE -eq 0 } -Seconds 30
}

# -- 2. API ------------------------------------------------------------------------
if ($Services -contains "api") {
    Write-Step "[2/4] API (port 8000)"
    if (Test-Port 8000) {
        Write-Skip "port 8000 is already in use"
    } else {
        $proc = Start-Hidden "API" $BackendDir "$Python -m uvicorn src.main:app --host $BindHost --port 8000 --reload" "backend_api"
        $null = Wait-Until "API" {
            try { $null = Invoke-RestMethod "http://127.0.0.1:8000/api/v1/health" -TimeoutSec 2; $true } catch { $false }
        } $proc "backend_api"
    }
    # The Unified Gateway on :8001 was merged into the API (2026-09-30).
    if (Test-Port 8001) {
        Write-Warn "port 8001 is in use - probably the retired Unified Gateway. Run .\stop_services.ps1 -Only api"
    }
}

# -- 3. Arq workers ----------------------------------------------------------------
if ($Services -contains "workers") {
    Write-Step "[3/4] Arq workers"
    $workers = @(
        @{ Name = "Arq worker"; Settings = "WorkerSettings"; Log = "arq_worker" },
        # Child runs have their own queue and worker (SA-07); without it they never run.
        @{ Name = "Arq child-run worker"; Settings = "ChildWorkerSettings"; Log = "arq_child_worker" }
    )
    foreach ($w in $workers) {
        if (Get-ArqWorker $w.Settings) {
            Write-Skip "$($w.Name) is already running"
        } else {
            $null = Start-Hidden $w.Name $BackendDir "$Python -m arq src.ai.worker.$($w.Settings)" $w.Log
        }
    }
}

# -- 4. Frontend -------------------------------------------------------------------
if ($Services -contains "frontend") {
    Write-Step "[4/4] Frontend (port 3000)"
    if (Test-Port 3000) {
        Write-Skip "port 3000 is already in use"
    } elseif (-not (Test-Path (Join-Path $FrontendDir "node_modules"))) {
        Write-Warn "frontend\node_modules is missing. Run: cd frontend; npm install --legacy-peer-deps"
    } else {
        $proc = Start-Hidden "Frontend" $FrontendDir "npm run dev" "frontend"
        $null = Wait-Until "Frontend" { Test-Port 3000 } $proc "frontend"
    }
}

# -- Summary -----------------------------------------------------------------------
Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Frontend: http://localhost:3000"
Write-Host "  API:      http://localhost:8000   (docs: /docs)"
Write-Host "  Logs:     logs\    Stop: .\stop_services.ps1"
try {
    $health = Invoke-RestMethod "http://127.0.0.1:8000/api/v1/health" -TimeoutSec 3
    Write-Host "  Health:   $($health.status) - workers $($health.worker.status)"
    if ($health.worker.status -eq "down") {
        Write-Host "            (a worker that has just started reports within ~10 s)" -ForegroundColor DarkGray
    }
} catch {
    Write-Host "  Health:   the API is not answering" -ForegroundColor Yellow
}
Write-Host "========================================" -ForegroundColor Cyan
