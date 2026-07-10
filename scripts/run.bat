@echo off
REM Launch the app from source.
setlocal
cd /d "%~dp0.."
call ".venv\Scripts\python.exe" run_app.py %*
endlocal
