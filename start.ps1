# ─────────────────────────────────────────────────────────────────
# vQA — Local Startup Script (Windows PowerShell)
# ─────────────────────────────────────────────────────────────────
# Usage:
#   .\start.ps1          # start backend + frontend
#   .\start.ps1 --stop   # stop all running vQA processes
#
# Feature-parity with start.sh:
#   - .env sourcing         - venv activation
#   - Port cleanup          - Health check polling
#   - Log streaming         - Graceful Ctrl+C shutdown
# ─────────────────────────────────────────────────────────────────

param(
    [switch]$Stop
)

$ErrorActionPreference = "Stop"

$SCRIPT_DIR    = $PSScriptRoot
$BACKEND_PORT  = 8000
$FRONTEND_PORT = 5173
$LOG_DIR       = Join-Path $SCRIPT_DIR ".logs"
$BACKEND_LOG   = Join-Path $LOG_DIR "backend.log"
$FRONTEND_LOG  = Join-Path $LOG_DIR "frontend.log"
$VENV_PYTHON   = Join-Path $SCRIPT_DIR ".venv\Scripts\python.exe"
$ENV_FILE      = Join-Path $SCRIPT_DIR ".env"

# ── Colours (ANSI — works in Windows Terminal / PowerShell 7) ─────
$C = @{
    Green  = "`e[0;32m"
    Yellow = "`e[1;33m"
    Red    = "`e[0;31m"
    Cyan   = "`e[0;36m"
    Bold   = "`e[1m"
    NC     = "`e[0m"
}

function Write-Color($Text, $Color = "NC") {
    Write-Host "$($C[$Color])$Text$($C['NC'])"
}

function Write-Header {
    Write-Host ""
    Write-Color "╔══════════════════════════════════════════╗" "Cyan"
    Write-Color "║   🔬 vQA — Autonomous Web Agent          ║" "Cyan"
    Write-Color "╚══════════════════════════════════════════╝" "Cyan"
    Write-Host ""
}

# ── Stop mode ─────────────────────────────────────────────────────
if ($Stop) {
    Write-Color "Stopping vQA processes..." "Yellow"
    Get-Process | Where-Object { $_.CommandLine -like "*uvicorn backend.main:app*" } | ForEach-Object {
        Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
        Write-Color "  ✓ Backend stopped" "Green"
    }
    Get-Process | Where-Object { $_.CommandLine -like "*vite*" -or ($_.Name -eq "node" -and $_.CommandLine -like "*dev*") } | ForEach-Object {
        Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
        Write-Color "  ✓ Frontend stopped" "Green"
    }
    Write-Host ""
    exit 0
}

Write-Header

# ── Create log directory and truncate stale logs ──────────────────
New-Item -ItemType Directory -Force -Path $LOG_DIR | Out-Null
"" | Set-Content $BACKEND_LOG
"" | Set-Content $FRONTEND_LOG

# ── Check prerequisites ───────────────────────────────────────────
Write-Color "Checking prerequisites..." "Bold"

if (Test-Path $VENV_PYTHON) {
    $PYTHON = $VENV_PYTHON
    Write-Host "  $($C['Green'])✓$($C['NC']) Python venv found (.venv)"
} else {
    # No project venv — fall back to system Python (e.g. pyenv global install)
    $PYTHON = (Get-Command python -ErrorAction SilentlyContinue).Source
    if (-not $PYTHON) {
        Write-Color "✗ No Python found. Install Python or create a venv:" "Red"
        Write-Host "  python -m venv .venv; .\.venv\Scripts\Activate.ps1; pip install -r backend\requirements.txt"
        exit 1
    }
    Write-Host "  $($C['Yellow'])⚠$($C['NC']) No .venv found — using system Python: $PYTHON"
}

# node_modules may be at repo root (Vite/monorepo) or under frontend/
$nodeModulesPath = if (Test-Path (Join-Path $SCRIPT_DIR "node_modules")) {
    Join-Path $SCRIPT_DIR "node_modules"
} else {
    Join-Path $SCRIPT_DIR "frontend\node_modules"
}
if (-not (Test-Path $nodeModulesPath)) {
    Write-Host "  $($C['Yellow'])⚠$($C['NC']) node_modules missing — running npm install..."
    npm install --silent
    Write-Host "  $($C['Green'])✓$($C['NC']) npm install complete"
}
Write-Host "  $($C['Green'])✓$($C['NC']) Frontend dependencies ready"

# ── Load .env into current process environment ────────────────────
# Mirrors: set -a; source .env; set +a in start.sh
if (Test-Path $ENV_FILE) {
    Get-Content $ENV_FILE | ForEach-Object {
        $line = $_.Trim()
        # Skip blank lines and comments
        if ($line -and $line -notmatch '^\s*#') {
            # Strip inline comments
            $line = ($line -split '\s+#')[0].Trim()
            if ($line -match '^([^=]+)=(.*)$') {
                $key   = $Matches[1].Trim()
                $value = $Matches[2].Trim().Trim('"').Trim("'")
                [System.Environment]::SetEnvironmentVariable($key, $value, "Process")
            }
        }
    }
    $skipSsm = [System.Environment]::GetEnvironmentVariable("SKIP_SSM", "Process")
    $ssmNote = if ($skipSsm) { " (SKIP_SSM=$skipSsm)" } else { "" }
    Write-Host "  $($C['Green'])✓$($C['NC']) Loaded .env$ssmNote"
}

# ── Kill any existing processes on those ports ────────────────────
foreach ($port in @($BACKEND_PORT, $FRONTEND_PORT)) {
    $procIds = (netstat -ano | Select-String ":$port\s" | ForEach-Object {
        ($_ -split '\s+')[-1]
    } | Sort-Object -Unique)
    foreach ($procId in $procIds) {
        if ($procId -match '^\d+$' -and $procId -ne "0") {
            Stop-Process -Id ([int]$procId) -Force -ErrorAction SilentlyContinue
        }
    }
}


Write-Host ""
Write-Color "Starting services..." "Bold"

# ── Backend ───────────────────────────────────────────────────────
# Start-Process avoids pyenv .bat shim issues and env var inheritance
# problems that affect Start-Job on Windows.
$backendProc = Start-Process -FilePath $PYTHON `
    -ArgumentList "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", $BACKEND_PORT, "--log-level", "info" `
    -WorkingDirectory $SCRIPT_DIR `
    -RedirectStandardOutput $BACKEND_LOG `
    -RedirectStandardError  (Join-Path $LOG_DIR "backend-err.log") `
    -NoNewWindow -PassThru

# Wait for backend to be ready
Write-Host -NoNewline "  Starting backend"
$backendReady = $false
for ($i = 0; $i -lt 90; $i++) {
    Start-Sleep -Seconds 1
    Write-Host -NoNewline "."
    try {
        $resp = Invoke-WebRequest -Uri "http://localhost:$BACKEND_PORT/health" -UseBasicParsing -TimeoutSec 1 -ErrorAction Stop
        if ($resp.StatusCode -eq 200) { $backendReady = $true; break }
    } catch {}
    if ($backendProc.HasExited) {
        Write-Host ""
        Write-Color "✗ Backend crashed. Last 20 lines of log:" "Red"
        if (Test-Path $BACKEND_LOG) { Get-Content $BACKEND_LOG -Tail 20 }
        exit 1
    }
}
Write-Host ""

# Health check — report Jira/S3 status (mirrors start.sh behaviour)
try {
    $health = Invoke-RestMethod -Uri "http://localhost:$BACKEND_PORT/api/health/ready" -TimeoutSec 3 -ErrorAction Stop
    $jiraStatus = $health.checks.jira
    $s3Status   = $health.checks.s3
} catch {
    $jiraStatus = "unknown"
    $s3Status   = "unknown"
}

Write-Host "  $($C['Green'])✓$($C['NC']) Backend running on http://localhost:$BACKEND_PORT"
$jiraColor = if ($jiraStatus -eq "connected") { "Green" } else { "Yellow" }
$s3Color   = if ($s3Status   -eq "connected") { "Green" } else { "Yellow" }
Write-Host "      Jira: $($C[$jiraColor])$jiraStatus$($C['NC'])"
Write-Host "      S3:   $($C[$s3Color])$s3Status$($C['NC'])"

# ── Frontend ──────────────────────────────────────────────────────
$frontendProc = Start-Process -FilePath "cmd.exe" `
    -ArgumentList "/c", "npm run dev" `
    -WorkingDirectory (Join-Path $SCRIPT_DIR "frontend") `
    -RedirectStandardOutput $FRONTEND_LOG `
    -RedirectStandardError  (Join-Path $LOG_DIR "frontend-err.log") `
    -NoNewWindow -PassThru

# Wait for frontend Vite to be ready
Write-Host -NoNewline "  Starting frontend"
for ($i = 0; $i -lt 20; $i++) {
    Start-Sleep -Seconds 1
    Write-Host -NoNewline "."
    if ((Test-Path $FRONTEND_LOG) -and (Get-Content $FRONTEND_LOG -Raw) -match "Local:") { break }
}
Write-Host ""
Write-Host "  $($C['Green'])✓$($C['NC']) Frontend running on http://localhost:$FRONTEND_PORT"

# ── Summary ───────────────────────────────────────────────────────
Write-Host ""
Write-Color "══════════════════════════════════════════" "Green"
Write-Color "  vQA is ready!" "Green"
Write-Color "══════════════════════════════════════════" "Green"
Write-Host ""
Write-Host "  $($C['Bold'])Dashboard:$($C['NC'])   http://localhost:$FRONTEND_PORT"
Write-Host "  $($C['Bold'])API Docs:$($C['NC'])    http://localhost:$BACKEND_PORT/docs"
Write-Host "  $($C['Bold'])Health:$($C['NC'])      http://localhost:$BACKEND_PORT/health"
Write-Host ""
Write-Host "  $($C['Bold'])Logs:$($C['NC'])"
Write-Host "    Backend:   .logs\backend.log"
Write-Host "    Frontend:  .logs\frontend.log"
Write-Host ""
Write-Color "  Press Ctrl+C to stop both services" "Yellow"
Write-Host ""

# ── Stream live logs + wait ────────────────────────────────────────
Write-Color "── Live Logs ─────────────────────────────" "Cyan"
try {
    # Stream both log files to console — mirrors `tail -f` in start.sh
    $tailBackend  = Start-Job -ScriptBlock { param($f) Get-Content $f -Wait -ErrorAction SilentlyContinue } -ArgumentList $BACKEND_LOG
    $tailFrontend = Start-Job -ScriptBlock { param($f) Get-Content $f -Wait -ErrorAction SilentlyContinue } -ArgumentList $FRONTEND_LOG

    while ($true) {
        Receive-Job $tailBackend  | ForEach-Object { Write-Host "[backend]  $_" }
        Receive-Job $tailFrontend | ForEach-Object { Write-Host "[frontend] $_" }
        # Exit early if either process has died
        if ($backendProc.HasExited)  { Write-Color "Backend process exited unexpectedly." "Red";  break }
        if ($frontendProc.HasExited) { Write-Color "Frontend process exited unexpectedly." "Red"; break }
        Start-Sleep -Milliseconds 500
    }
} finally {
    # ── Cleanup on Ctrl+C ─────────────────────────────────────────
    Write-Host ""
    Write-Color "Shutting down vQA..." "Yellow"
    Stop-Process -Id $backendProc.Id  -Force -ErrorAction SilentlyContinue
    Stop-Process -Id $frontendProc.Id -Force -ErrorAction SilentlyContinue
    Stop-Job  $tailBackend, $tailFrontend -ErrorAction SilentlyContinue
    Remove-Job $tailBackend, $tailFrontend -ErrorAction SilentlyContinue
    Write-Host "  $($C['Green'])✓$($C['NC']) Stopped"
}
