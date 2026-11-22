@echo off
setlocal
cd /d "%~dp0"

:: 1. Remove broken .venv if pip is missing inside it
if exist ".venv" (
    .venv\Scripts\python.exe -m pip --version >nul 2>&1
    if errorlevel 1 (
        echo Removing broken .venv...
        rmdir /s /q ".venv"
    )
)

:: 2. Ensure clean Python 3.12 is installed via PyManager
py -3.12 --version >nul 2>&1
if errorlevel 1 (
    echo Installing clean Python 3.12 via PyManager...
    py install 3.12
)

:: 3. Create .venv using Python 3.12
if not exist ".venv\Scripts\python.exe" (
    echo Creating .venv with Python 3.12...
    py -3.12 -m venv .venv
)

if not exist ".venv\Scripts\python.exe" (
    echo ERROR: Could not create .venv with Python 3.12.
    echo Try running manually in Command Prompt:  py install 3.12
    pause
    exit /b 1
)

echo Upgrading pip inside .venv...
.venv\Scripts\python.exe -m pip install --upgrade pip

echo Installing required packages...
.venv\Scripts\python.exe -m pip install -r studio\requirements.txt pyinstaller
if %errorlevel% neq 0 (
    echo ERROR: Package installation failed.
    pause
    exit /b 1
)

set "EXTRA_DATA="
if exist "blocks.json" (
    set "EXTRA_DATA=--add-data blocks.json;."
)

echo Building OpenVAG_Studio.exe...
.venv\Scripts\python.exe -m PyInstaller --noconfirm --onefile --windowed --uac-admin ^
  --name "OpenVAG_Studio" ^
  --paths "." ^
  --add-data "studio\static;studio\static" ^
  %EXTRA_DATA% ^
  --hidden-import "uvicorn.logging" ^
  --hidden-import "uvicorn.loops.auto" ^
  --hidden-import "uvicorn.protocols.http.auto" ^
  --hidden-import "uvicorn.protocols.websockets.auto" ^
  --hidden-import "uvicorn.lifespan.on" ^
  --hidden-import "serial.tools.list_ports" ^
  studio\launcher.py

if %errorlevel% neq 0 (
    echo.
    echo BUILD FAILED! Check the error messages above.
    pause
    exit /b 1
)

echo.
echo Build complete! Hand over: dist\OpenVAG_Studio.exe
pause