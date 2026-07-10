@echo off
REM Build the standalone app with PyInstaller (output in dist\EasyVideoConverter).
setlocal
cd /d "%~dp0.."

echo Cleaning previous build...
if exist "build" rmdir /s /q "build"
if exist "dist\EasyVideoConverter" rmdir /s /q "dist\EasyVideoConverter"

echo Building with PyInstaller...
call ".venv\Scripts\python.exe" -m PyInstaller --noconfirm EasyVideoConverter.spec

echo.
echo Build complete: dist\EasyVideoConverter\EasyVideoConverter.exe
endlocal
