@echo off
REM Create the virtual environment and install dependencies.
setlocal
cd /d "%~dp0.."

if not exist ".venv" (
    echo Creating virtual environment...
    python -m venv .venv
)

echo Installing dependencies...
call ".venv\Scripts\python.exe" -m pip install --upgrade pip
call ".venv\Scripts\python.exe" -m pip install -r requirements.txt

if not exist "vendor\ffmpeg\ffmpeg.exe" (
    echo Fetching bundled FFmpeg...
    powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\get-ffmpeg.ps1"
)

echo.
echo Setup complete. Run scripts\run.bat to start the app.
endlocal
