@echo off
REM Build the Windows installer with Inno Setup (requires ISCC.exe).
setlocal
cd /d "%~dp0.."

set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" (
    echo ERROR: Inno Setup 6 not found. Install it from https://jrsoftware.org/isdl.php
    exit /b 1
)

if not exist "dist\EasyVideoConverter\EasyVideoConverter.exe" (
    echo ERROR: build the app first with scripts\build.bat
    exit /b 1
)

echo Building installer...
"%ISCC%" "installer\EasyVideoConverter.iss"

echo.
echo Installer written to dist\
endlocal
