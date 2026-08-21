@echo off
setlocal

cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo Python was not found on PATH.
    echo Install Python 3.10+ from https://www.python.org/downloads/
    echo and make sure "Add python.exe to PATH" is checked during setup.
    pause
    exit /b 1
)

if not exist venv (
    echo Creating virtual environment...
    python -m venv venv
)

call venv\Scripts\activate.bat

echo Installing dependencies...
pip install -r requirements.txt -r requirements-build.txt
if errorlevel 1 (
    echo Dependency install failed - see the output above.
    pause
    exit /b 1
)

echo Building QRLinkDecoder.exe...
pyinstaller --onefile --windowed --name QRLinkDecoder gui.py
if not exist dist\QRLinkDecoder.exe (
    echo Build failed - see the output above.
    pause
    exit /b 1
)

echo.
echo Build complete: dist\QRLinkDecoder.exe
echo Launching it now...
start "" "dist\QRLinkDecoder.exe"
