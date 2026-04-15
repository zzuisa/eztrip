Param(
  [string]$CondaBat = $env:CONDA_BAT,
  [string]$PythonBin = $env:PYTHON_BIN
)

$ErrorActionPreference = 'Stop'

# =========================================================
# Guardian-style startup script for backend + frontend
# Usage:
#   powershell -ExecutionPolicy Bypass -File .\start-dev.ps1
# Optional:
#   $env:CONDA_BAT='D:\Anaconda3\condabin\conda.bat'
#   $env:PYTHON_BIN='python'
# =========================================================

$RootDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendDir = Join-Path $RootDir 'backend'
$FrontendDir = Join-Path $RootDir 'frontend'
$LogDir = Join-Path $RootDir 'logs'
$BackendLog = Join-Path $LogDir 'backend.log'
$FrontendLog = Join-Path $LogDir 'frontend.log'
$BackendPidFile = Join-Path $LogDir 'backend.pid'
$FrontendPidFile = Join-Path $LogDir 'frontend.pid'

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

if (-not (Test-Path $BackendDir)) { throw "Backend directory not found: $BackendDir" }
if (-not (Test-Path $FrontendDir)) { throw "Frontend directory not found: $FrontendDir" }

if (-not $PythonBin) { $PythonBin = 'python' }

Write-Host "[INFO] Root: $RootDir"
Write-Host "[INFO] Backend: $BackendDir"
Write-Host "[INFO] Frontend: $FrontendDir"
Write-Host "[INFO] Logs: $LogDir"

$BackendScript = @"
chcp 65001 >nul
cd /d "$BackendDir"
set PYTHONIOENCODING=utf-8
$(if ($CondaBat -and (Test-Path $CondaBat)) { "call `"$CondaBat`" activate py310 && " } else { '' })$PythonBin -m uvicorn app.api.main:app --reload --host 0.0.0.0 --port 8881
"@

$FrontendScript = @"
chcp 65001 >nul
cd /d "$FrontendDir"
npm run dev
"@

Write-Host "[INFO] Starting backend..."
$backendProc = Start-Process -FilePath 'cmd.exe' -ArgumentList '/c', $BackendScript -PassThru -WindowStyle Minimized -RedirectStandardOutput $BackendLog -RedirectStandardError $BackendLog
$backendProc.Id | Set-Content -Path $BackendPidFile -Encoding UTF8

Write-Host "[INFO] Starting frontend..."
$frontendProc = Start-Process -FilePath 'cmd.exe' -ArgumentList '/c', $FrontendScript -PassThru -WindowStyle Minimized -RedirectStandardOutput $FrontendLog -RedirectStandardError $FrontendLog
$frontendProc.Id | Set-Content -Path $FrontendPidFile -Encoding UTF8

Write-Host ''
Write-Host '[DONE] Guardian startup launched.'
Write-Host '       Backend:  http://localhost:8881'
Write-Host '       Frontend: http://localhost:5173'
Write-Host ''
Write-Host "[INFO] Logs:`n       Backend  -> $BackendLog`n       Frontend -> $FrontendLog"
Write-Host ''
Write-Host '[INFO] Press Ctrl+C to stop this session; child processes may keep running if terminal is closed unexpectedly.'

Register-EngineEvent PowerShell.Exiting -Action {
  try {
    if (Test-Path $using:BackendPidFile) {
      Stop-Process -Id ([int](Get-Content $using:BackendPidFile)) -Force -ErrorAction SilentlyContinue
    }
    if (Test-Path $using:FrontendPidFile) {
      Stop-Process -Id ([int](Get-Content $using:FrontendPidFile)) -Force -ErrorAction SilentlyContinue
    }
  } catch {}
} | Out-Null

while ($true) { Start-Sleep -Seconds 1 }
