@echo off
setlocal

REM =========================================================
REM Quick start script for backend + frontend
REM Usage:
REM   - Double click this file, or run: start-dev.bat
REM Optional:
REM   - set CONDA_BAT to your conda.bat full path before running
REM =========================================================

set "ROOT_DIR=%~dp0"
set "BACKEND_DIR=%ROOT_DIR%backend"
set "FRONTEND_DIR=%ROOT_DIR%frontend"

if not exist "%BACKEND_DIR%" (
  echo [ERROR] Backend directory not found: "%BACKEND_DIR%"
  exit /b 1
)

if not exist "%FRONTEND_DIR%" (
  echo [ERROR] Frontend directory not found: "%FRONTEND_DIR%"
  exit /b 1
)

REM Default conda path (can be overridden by environment variable)
if "%CONDA_BAT%"=="" set "CONDA_BAT=D:\Anaconda3\condabin\conda.bat"

echo [INFO] Root: %ROOT_DIR%
echo [INFO] Backend: %BACKEND_DIR%
echo [INFO] Frontend: %FRONTEND_DIR%
echo [INFO] Conda: %CONDA_BAT%
echo.

if exist "%CONDA_BAT%" (
  echo [INFO] Starting backend in a new window...
  start "TripPlanner Backend" cmd /k "chcp 65001 && call %CONDA_BAT% activate py310 && cd /d %BACKEND_DIR% && set PYTHONIOENCODING=utf-8 && uvicorn app.api.main:app --reload --host 0.0.0.0 --port 8000"
) else (
  echo [WARN] conda.bat not found at "%CONDA_BAT%".
  echo [WARN] Trying to run backend without conda activation...
  start "TripPlanner Backend" cmd /k "chcp 65001 && cd /d %BACKEND_DIR% && set PYTHONIOENCODING=utf-8 && uvicorn app.api.main:app --reload --host 0.0.0.0 --port 8000"
)

echo [INFO] Starting frontend in a new window...
start "TripPlanner Frontend" cmd /k "chcp 65001 && cd /d %FRONTEND_DIR% && npm run dev"

echo.
echo [DONE] Startup commands launched.
echo         Backend:  http://localhost:8000
echo         Frontend: http://localhost:5173
echo.
echo Press any key to close this launcher window...
pause >nul

endlocal
