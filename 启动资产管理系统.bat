@echo off
cd /d "%~dp0"

echo [Asset Management System] Starting...
echo Local:  http://localhost:8000
echo.

echo Checking Python...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python not found. Please install Python and add it to PATH.
    pause
    exit /b 1
)

echo Starting server in background...
start "AssetMS_Server" /MIN python main.py

echo Waiting for server to start...
timeout /t 4 /nobreak >nul

echo Opening browser...
start http://localhost:8000

echo.
echo If browser does not open, visit: http://localhost:8000
echo You can close this window. To stop the server, close the "AssetMS_Server" window.
pause
