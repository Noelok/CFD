@echo off
setlocal

echo ===================================================
echo   FluidX3D Launcher
echo ===================================================

:: 1. Check if cl.exe is already available
where cl >nul 2>nul
if %errorlevel% equ 0 (
    echo [INFO] cl.exe found in PATH.
    goto :RUN_PYTHON
)

:: 2. Search for vcvars64.bat (VS 2022/2019)
echo [INFO] cl.exe not found. Searching for Visual Studio Build Tools...

set "vcvars="

:: VS 2022
if exist "C:\Program Files\Microsoft Visual Studio\2022\Professional\VC\Auxiliary\Build\vcvars64.bat" set "vcvars=C:\Program Files\Microsoft Visual Studio\2022\Professional\VC\Auxiliary\Build\vcvars64.bat"
if exist "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat" set "vcvars=C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat"
if exist "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat" set "vcvars=C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat"
if exist "C:\Program Files\Microsoft Visual Studio\2022\Enterprise\VC\Auxiliary\Build\vcvars64.bat" set "vcvars=C:\Program Files\Microsoft Visual Studio\2022\Enterprise\VC\Auxiliary\Build\vcvars64.bat"

:: VS 2019
if not defined vcvars (
    if exist "C:\Program Files (x86)\Microsoft Visual Studio\2019\BuildTools\VC\Auxiliary\Build\vcvars64.bat" set "vcvars=C:\Program Files (x86)\Microsoft Visual Studio\2019\BuildTools\VC\Auxiliary\Build\vcvars64.bat"
    if exist "C:\Program Files (x86)\Microsoft Visual Studio\2019\Community\VC\Auxiliary\Build\vcvars64.bat" set "vcvars=C:\Program Files (x86)\Microsoft Visual Studio\2019\Community\VC\Auxiliary\Build\vcvars64.bat"
)

if defined vcvars (
    echo [INFO] Found VS Build Tools at: "%vcvars%"
    echo [INFO] Initializing environment...
    call "%vcvars%" >nul
) else (
    echo [WARNING] Could not find Visual Studio Build Tools.
    echo [WARNING] Compiling the backend definition might fail.
)

:RUN_PYTHON
echo.
echo [INFO] Starting Application...
python main.py
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Application exited with error code %errorlevel%
    pause
    exit /b %errorlevel%
)

endlocal
