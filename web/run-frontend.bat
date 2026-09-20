@echo off
REM ============================================================
REM  Tree - AirPod Yoga.  Double-click this file to run the
REM  frontend on its own, with no AirPods and no Mac.
REM
REM  Port 8080 on purpose: Bridge's real server uses 8765, and
REM  this must never fight it for a port during a demo.
REM ============================================================
cd /d "%~dp0"

python --version >nul 2>&1
if errorlevel 1 (
  echo.
  echo   Python was not found on this computer.
  echo   Install it from https://python.org and tick
  echo   "Add Python to PATH" during setup, then try again.
  echo.
  pause
  exit /b 1
)

start "" /b powershell -NoProfile -Command "Start-Sleep -Seconds 2; Start-Process 'http://localhost:8080/?mock=1'"

echo.
echo   ============================================
echo     Tree - AirPod Yoga
echo   ============================================
echo.
echo     Your browser opens in a moment. If it does
echo     not, go to:
echo.
echo       http://localhost:8080/?mock=1
echo.
echo     Hold SPACE to hold the pose and grow the
echo     tree. Move the mouse to swing the arm.
echo.
echo     Keep this window open while you use it.
echo     Close it to stop.
echo.
echo   ============================================
echo.

python -m http.server 8080 --directory .
